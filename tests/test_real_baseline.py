"""Layer 6b 裸基线评测的离线用例:用 MockBackend 精确控制两条基线臂的行为。"""
import json

from mycoder.config import Config
from mycoder.eval.raw_baseline import RawBaselineRunner, _parse_block_path
from mycoder.models import MockBackend


def _write_tasks(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({
        "tasks": [{
            "task_id": "rb-test",
            "goal": "创建 result.txt,内容包含 done",
            "setup_files": {"base.txt": "hello\n"},
            "expect": {"files_created": ["result.txt"],
                       "file_contains": {"result.txt": "done"}},
        }]
    }), encoding="utf-8")
    return path


def test_parse_block_path_prefers_path_keyword():
    assert _parse_block_path("python path=src/utils.py") == "src/utils.py"
    assert _parse_block_path("text result.txt") == "result.txt"
    assert _parse_block_path("python") == ""


def test_single_shot_writes_code_blocks_and_passes(tmp_path):
    def factory(_config):
        return MockBackend(script=[
            {"content": "说明\n```python path=result.txt\ndone\n```\n"},
        ])

    runner = RawBaselineRunner(Config(), output_dir=tmp_path / "out",
                               tasks_path=_write_tasks(tmp_path),
                               backend_factory=factory)
    report = runner.run()
    assert report["ok"] is True
    assert report["arms"]["single_shot"]["passed"] == 1
    row = next(r for r in report["results"] if r["arm"] == "single_shot")
    assert row["assertions_ok"] is True
    assert row["extracted_files"] == ["result.txt"]
    assert row["metrics"]["model_calls"] == 1
    assert (tmp_path / "out" / "real_baseline_report.json").exists()


def test_naive_loop_executes_tool_calls_and_passes(tmp_path):
    def factory(_config):
        return MockBackend(script=[
            {"tool_calls": [{"name": "file_write", "arguments": {
                "path": "result.txt", "content": "done\n"}}]},
            {"content": "已创建 result.txt"},
        ])

    runner = RawBaselineRunner(Config(), output_dir=tmp_path / "out",
                               tasks_path=_write_tasks(tmp_path),
                               backend_factory=factory)
    report = runner.run()
    assert report["arms"]["naive_loop"]["passed"] == 1
    row = next(r for r in report["results"] if r["arm"] == "naive_loop")
    assert row["assertions_ok"] is True
    assert row["metrics"]["model_calls"] == 2
    assert row["metrics"]["tool_calls"] == 1
    assert row["metrics"]["write_calls"] == 1
    assert row["tool_call_names"] == ["file_write"]


def test_naive_loop_tool_schemas_exclude_shell_and_memory(tmp_path):
    captured = []

    def factory(_config):
        backend = MockBackend(script=[{"content": "完成"}])
        original = backend.complete

        def complete(messages, tools=None, temperature=0.0):
            captured.append([t["name"] for t in (tools or [])])
            return original(messages, tools, temperature)

        backend.complete = complete
        return backend

    runner = RawBaselineRunner(Config(), output_dir=tmp_path / "out",
                               tasks_path=_write_tasks(tmp_path),
                               backend_factory=factory)
    runner.run()
    naive_tools = captured[-1]  # naive_loop 是第二条臂
    assert "file_write" in naive_tools
    assert "shell_exec" not in naive_tools
    assert "memory_query" not in naive_tools


def test_comparison_includes_harness_reference(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "real_report.json").write_text(json.dumps({
        "results": [{"task_id": "rb-test", "passed": True, "judge": {"score": 4}}]
    }), encoding="utf-8")

    def factory(_config):
        return MockBackend(script=[
            {"content": "```python path=result.txt\ndone\n```"},
        ])

    runner = RawBaselineRunner(Config(), output_dir=out_dir,
                               tasks_path=_write_tasks(tmp_path),
                               backend_factory=factory)
    report = runner.run()
    assert report["comparison"][0]["harness"] is True
    assert report["comparison"][0]["single_shot"] is True
    assert "harness 参考" in report["summary"]


def test_baseline_skips_default_mock(tmp_path):
    report = RawBaselineRunner(Config(), output_dir=tmp_path / "out").run()
    assert report["skipped"] is True
    assert "local_openai" in report["summary"]
