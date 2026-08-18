"""Harness 主循环端到端测试:完成/工件/安全拦截/去重/记忆/恢复。"""
import pytest

from mycoder.safety import DenyAllProvider
from mycoder.state import TaskInput

WRITE_SCRIPT = [
    {"tool_calls": [{"name": "file_write",
                     "arguments": {"path": "out.py", "content": "print('hi')\n"}}]},
    {"content": "已创建 out.py。"},
]


@pytest.fixture
def task():
    return TaskInput(task_id="t-test", goal="创建 out.py")


class TestRunFlow:
    def test_completes(self, make_harness, task):
        h = make_harness(script=WRITE_SCRIPT)
        r = h.run(task)
        assert r.status == "completed"
        assert "out.py" in r.final_answer
        assert h.workspace.read_text("out.py") == "print('hi')\n"

    def test_produces_three_artifacts(self, make_harness, task):
        h = make_harness(script=WRITE_SCRIPT)
        h.run(task)
        d = h.artifacts.task_dir(task.task_id)
        assert (d / "trajectory.jsonl").exists()
        assert (d / "metrics.json").exists()
        assert (d / "report.md").exists()

    def test_metrics_recorded(self, make_harness, task):
        h = make_harness(script=WRITE_SCRIPT)
        r = h.run(task)
        assert r.metrics["steps"] == 2
        assert r.metrics["write_calls"] == 1
        assert r.metrics["tool_calls"] == 1
        assert r.metrics["files_remembered"] >= 1

    def test_max_steps(self, make_harness, task):
        # 脚本很长但 max_steps 很小 -> max_steps 终止
        script = [{"tool_calls": [{"name": "file_write",
                                   "arguments": {"path": "x.py", "content": "1"}}]}
                  for _ in range(10)] + [{"content": "结束"}]
        h = make_harness(script=script, **{"harness.max_steps": 3})
        r = h.run(task)
        assert r.status == "max_steps"

    def test_unknown_tool_intercepted(self, make_harness, task):
        h = make_harness(script=[{"tool_calls": [{"name": "hack_tool", "arguments": {}}]},
                                 {"content": "end"}])
        r = h.run(task)
        step = r.steps[0]
        assert step.tool_calls[0].status == "denied"

    def test_invalid_params_intercepted(self, make_harness, task):
        h = make_harness(script=[
            {"tool_calls": [{"name": "file_read", "arguments": {}}]},  # 缺 path
            {"content": "end"}])
        r = h.run(task)
        assert r.steps[0].tool_calls[0].status == "denied"


class TestSafetyInHarness:
    def test_path_escape_blocked_in_run(self, make_harness, task):
        h = make_harness(script=[
            {"tool_calls": [{"name": "file_read", "arguments": {"path": "../secret"}}]},
            {"content": "end"}])
        r = h.run(task)
        assert r.steps[0].tool_calls[0].status == "denied"
        assert "逃逸" in r.steps[0].tool_calls[0].error

    def test_shell_denied_by_policy(self, make_harness, task):
        h = make_harness(script=[
            {"tool_calls": [{"name": "shell_exec", "arguments": {"command": "echo hi"}}]},
            {"content": "end"}], approver=DenyAllProvider())
        r = h.run(task)
        assert r.steps[0].tool_calls[0].status == "denied"
        assert "审批" in r.steps[0].tool_calls[0].error

    def test_shell_approved(self, make_harness, task):
        h = make_harness(script=[
            {"tool_calls": [{"name": "shell_exec", "arguments": {"command": "echo hi"}}]},
            {"content": "end"}])
        r = h.run(task)
        assert r.steps[0].tool_calls[0].status == "ok"

    def test_redaction_in_trajectory(self, make_harness, task):
        h = make_harness(script=[
            {"tool_calls": [{"name": "file_write",
                             "arguments": {"path": "s.py",
                                           "content": "token=sk-abcdefghijklmnopqrstuvwxyz"}}]},
            {"content": "end"}])
        h.run(task)
        raw = (h.artifacts.task_dir(task.task_id) / "trajectory.jsonl").read_text("utf-8")
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in raw


class TestDedupInHarness:
    def test_repeated_read_uses_cache(self, make_harness, config):
        script = [
            {"tool_calls": [{"name": "file_read", "arguments": {"path": "r.py"}}]},
            {"tool_calls": [{"name": "file_read", "arguments": {"path": "r.py"}}]},
            {"content": "end"}]
        h = make_harness(script=script)
        h.workspace.write_text("r.py", "content")
        r = h.run(TaskInput("t-dedup", "读两次"))
        metrics = r.metrics
        assert metrics["read_cache_hits"] == 1
        assert metrics["read_calls"] == 1  # 只真正读了一次盘


class TestMemoryInHarness:
    def test_followup_injects_memory(self, make_harness):
        from mycoder.state import TaskInput as TI
        parent = TI(task_id="parent", goal="建 utils.py", files_hint=["utils.py"])
        child = TI(task_id="child", goal="用 utils", files_hint=["utils.py"],
                   follow_up_of="parent")
        h = make_harness(script=[
            {"tool_calls": [{"name": "file_write",
                             "arguments": {"path": "utils.py",
                                           "content": "def add(a,b): return a+b\n"}}]},
            {"content": "完成"}])
        h.run(parent)
        # 第二次用同 memory 根的新 harness 模拟 follow-up
        h2 = make_harness(script=[
            {"tool_calls": [{"name": "memory_query", "arguments": {"query": "utils"}}]},
            {"content": "用记忆完成"}])
        r2 = h2.run(child)
        assert r2.status == "completed"
        assert r2.metrics["read_calls"] == 0  # 没有重读文件
        assert h2.context.memory_block  # 记忆块已注入


class TestResumeFlow:
    def test_interrupt_resume_continues(self, make_harness):
        script = [
            {"tool_calls": [{"name": "file_write", "arguments": {"path": "m/s1.txt", "content": "1"}}]},
            {"tool_calls": [{"name": "file_write", "arguments": {"path": "m/s2.txt", "content": "2"}}]},
            {"tool_calls": [{"name": "file_write", "arguments": {"path": "m/s3.txt", "content": "3"}}]},
            {"content": "全部完成。"}]
        h = make_harness(script=script)
        r1 = h.run(TaskInput("t-resume", "分步构建"), stop_after_steps=1)
        assert r1.status == "interrupted"
        # 换个新 harness 续跑(模拟进程重启)
        h2 = make_harness(script=script)
        r2 = h2.resume("t-resume")
        assert r2.status == "completed"
        assert r2.final_answer == "全部完成。"
        # 三份文件都应存在(含被中断前的那步与恢复后的两步)
        for f in ("m/s1.txt", "m/s2.txt", "m/s3.txt"):
            assert h2.workspace.exists(f)

    def test_resume_detects_drift(self, make_harness):
        script = [
            {"tool_calls": [{"name": "file_write", "arguments": {"path": "m/s1.txt", "content": "1"}}]},
            {"tool_calls": [{"name": "file_write", "arguments": {"path": "m/s2.txt", "content": "2"}}]},
            {"content": "完成。"}]
        h = make_harness(script=script)
        h.run(TaskInput("t-drift", "分步构建"), stop_after_steps=1)
        # 外部改动工作区
        p = h.workspace.root / "m" / "s1.txt"
        p.write_text("被外部修改", encoding="utf-8")
        h2 = make_harness(script=script)
        r2 = h2.resume("t-drift")
        assert r2.drift is not None and r2.drift["is_drift"]
        # 漂移检测返回相对路径(含子目录)
        assert any("s1.txt" in path for path in r2.drift["modified"])

    def test_resume_missing_checkpoint(self, make_harness):
        h = make_harness()
        r = h.resume("nope")
        assert r.status == "error"
