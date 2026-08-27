import json

from mycoder.config import Config
from mycoder.eval.judge import LLMJudge
from mycoder.eval.real import RealTaskRunner
from mycoder.models import MockBackend


def test_judge_parses_strict_json():
    backend = MockBackend(script=[{"content": '{"pass": true, "score": 4, "reasoning": "覆盖充分"}'}])
    verdict = LLMJudge(backend).judge("实现函数", {"a.py": "def a(): pass"}, "有测试")
    assert verdict.passed is True
    assert verdict.score == 4
    assert verdict.parse_ok is True


def test_judge_parse_failure_is_honest():
    backend = MockBackend(script=[{"content": "这不是 JSON"}])
    verdict = LLMJudge(backend).judge("实现函数", {}, "")
    assert verdict.passed is False
    assert verdict.score == 0
    assert verdict.parse_ok is False


def test_real_runner_combines_assertions_and_judge(tmp_path):
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps({
        "tasks": [{
            "task_id": "rt-test",
            "goal": "创建 result.txt",
            "expect": {"files_created": ["result.txt"], "file_contains": {"result.txt": "done"}},
            "judge": {"rubric": "文件内容正确"},
        }]
    }), encoding="utf-8")

    def agent_factory(_config):
        return MockBackend(script=[
            {"tool_calls": [{"name": "file_write", "arguments": {
                "path": "result.txt", "content": "done\n"
            }}]},
            {"content": "已完成"},
        ])

    judge_backend = MockBackend(script=[
        {"content": '{"pass": true, "score": 5, "reasoning": "满足标准"}'},
    ])
    cfg = Config()
    runner = RealTaskRunner(cfg, output_dir=tmp_path / "out", tasks_path=tasks_path,
                            backend_factory=agent_factory, judge_backend=judge_backend)
    report = runner.run()
    assert report["ok"] is True
    assert report["passed"] == 1
    assert report["results"][0]["assertions_ok"] is True
    assert report["results"][0]["judge"]["score"] == 5
    assert (tmp_path / "out" / "real_report.json").exists()


def test_real_runner_skips_default_mock(tmp_path):
    report = RealTaskRunner(Config(), output_dir=tmp_path / "out").run()
    assert report["skipped"] is True
    assert "local_openai" in report["summary"]
