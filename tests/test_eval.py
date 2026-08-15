"""四层评测 + benchmark 数据完整性测试。"""
import json
from pathlib import Path

import pytest

from mycoder.config import Config
from mycoder.eval import EvalRunner, by_layer, load_benchmarks

BM_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "tasks.json"


@pytest.fixture(scope="module")
def benchmarks():
    return load_benchmarks(BM_PATH)


class TestBenchmarkData:
    def test_twelve_tasks(self, benchmarks):
        assert len(benchmarks) == 12

    def test_unique_ids(self, benchmarks):
        ids = [t["task_id"] for t in benchmarks]
        assert len(set(ids)) == len(ids)

    def test_layer_distribution(self, benchmarks):
        assert len(by_layer(benchmarks, "regression")) == 4
        assert len(by_layer(benchmarks, "context")) == 3
        assert len(by_layer(benchmarks, "memory")) == 4
        assert len(by_layer(benchmarks, "resume")) == 1

    def test_all_have_scripts(self, benchmarks):
        for t in benchmarks:
            assert t.get("script"), t["task_id"]

    def test_memory_pairs(self, benchmarks):
        mem = by_layer(benchmarks, "memory")
        parents = {t["task_id"] for t in mem if not t.get("follow_up_of")}
        children = [t for t in mem if t.get("follow_up_of")]
        assert len(parents) == 2 and len(children) == 2
        for c in children:
            assert c["follow_up_of"] in parents
            assert c.get("control_script")  # 对照组脚本必须存在

    def test_json_valid(self):
        data = json.loads(BM_PATH.read_text(encoding="utf-8"))
        assert "tasks" in data


class TestEvalLayers:
    @pytest.fixture(scope="class")
    def reports(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("eval")
        runner = EvalRunner(Config(), output_dir=str(out), benchmark_path=BM_PATH)
        return runner.run_suite("all")

    def test_regression_layer(self, reports):
        assert reports["regression"]["ok"] is True
        assert reports["regression"]["summary"].startswith("4/4")

    def test_context_layer(self, reports):
        assert reports["context"]["ok"] is True
        assert "平均压缩率" in reports["context"]["summary"]
        assert "100%" in reports["context"]["summary"]  # 预算内完成率

    def test_memory_layer(self, reports):
        assert reports["memory"]["ok"] is True
        assert "0" in reports["memory"]["summary"]  # 重读归零

    def test_resume_layer(self, reports):
        assert reports["resume"]["ok"] is True
        assert reports["resume"]["accuracy"] == 1.0

    def test_all_layers_present(self, reports):
        assert set(reports) == {"regression", "context", "memory", "resume"}

    def test_deterministic_repeat(self, tmp_path):
        out1 = tmp_path / "e1"
        out2 = tmp_path / "e2"
        r1 = EvalRunner(Config(), output_dir=str(out1), benchmark_path=BM_PATH).run_suite("context")
        r2 = EvalRunner(Config(), output_dir=str(out2), benchmark_path=BM_PATH).run_suite("context")
        assert r1["context"]["summary"] == r2["context"]["summary"]


class TestReportWriting:
    def test_write_report_files(self, tmp_path):
        runner = EvalRunner(Config(), output_dir=str(tmp_path / "out"), benchmark_path=BM_PATH)
        reports = runner.run_suite("context")
        runner.write_report(reports)
        assert (tmp_path / "out" / "report.json").exists()
        assert (tmp_path / "out" / "report.md").exists()