"""评测加固:数据集完整性、动态指标和回归灵敏度测试。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from mycoder.config import Config
from mycoder.eval import EvalRunner, by_layer, load_benchmarks

ROOT = Path(__file__).resolve().parent.parent
BM_DIR = ROOT / "benchmarks"
BM_PATH = BM_DIR / "tasks.json"
GEN_PATH = BM_DIR / "tasks.generated.json"
RETRIEVAL_PATH = BM_DIR / "retrieval.json"


@pytest.fixture(scope="module")
def benchmarks():
    # 默认加载手写核心+固定 seed 冻结的生成数据,这是实际评测集
    return load_benchmarks()


@pytest.fixture(scope="module")
def retrieval_tasks():
    return load_benchmarks(RETRIEVAL_PATH)


class TestBenchmarkData:
    def test_generated_data_is_frozen_and_valid(self):
        assert GEN_PATH.exists(), "缺少冻结的生成基准;运行 python benchmarks/generators.py"
        data = json.loads(GEN_PATH.read_text(encoding="utf-8"))
        assert data["tasks"]

    def test_unique_ids(self, benchmarks):
        ids = [t["task_id"] for t in benchmarks]
        assert len(set(ids)) == len(ids)

    def test_each_execution_layer_has_at_least_fifteen_tasks(self, benchmarks):
        # resume 是 3 个任务 x 多停点 x 5 种漂移类型的场景矩阵,在运行层达到 >=15。
        assert len(by_layer(benchmarks, "regression")) >= 15
        assert len(by_layer(benchmarks, "context")) >= 15
        assert len(by_layer(benchmarks, "memory")) >= 15
        resume = by_layer(benchmarks, "resume")
        assert len(resume) >= 3
        scenario_count = sum(
            len((t.get("resume") or {}).get("stop_points", []))
            * (1 + len((t.get("resume") or {}).get("drift_types", [])))
            for t in resume)
        assert scenario_count >= 15

    def test_negative_or_boundary_coverage_is_at_least_twenty_percent(self, benchmarks):
        scored = [t for t in benchmarks if t["layer"] in {"regression", "context", "memory"}]
        defensive = [t for t in scored if t.get("kind") in {"negative", "boundary"}]
        assert len(defensive) / len(scored) >= 0.2
        assert sum(t.get("kind") == "negative" for t in by_layer(benchmarks, "regression")) >= 5

    def test_all_have_scripts(self, benchmarks):
        for t in benchmarks:
            assert t.get("script"), t["task_id"]

    def test_memory_scenario_matrix_and_control_pairs(self, benchmarks):
        mem = by_layer(benchmarks, "memory")
        parents = {t["task_id"] for t in mem if not t.get("follow_up_of")}
        children = [t for t in mem if t.get("follow_up_of")]
        assert len(parents) >= 5
        assert len(children) >= 10
        assert {"fresh_hit", "fresh", "stale", "wrong", "missing"} <= {
            c.get("memory_scenario", "fresh_hit") for c in children
        }
        for c in children:
            assert c["follow_up_of"] in parents
            assert c.get("control_script"), c["task_id"]

    def test_retrieval_dataset_has_size_and_type_coverage(self, retrieval_tasks):
        queries = [q for t in retrieval_tasks for q in t["queries"]]
        kinds = Counter(q["type"] for q in queries)
        assert len(queries) >= 30
        assert {"exact", "synonym", "distractor", "empty"} <= set(kinds)
        assert all(count >= 4 for count in kinds.values())
        assert all(20 <= len(t["corpus"]) <= 50 for t in retrieval_tasks)

    def test_json_valid(self):
        assert json.loads(BM_PATH.read_text(encoding="utf-8"))["tasks"]
        assert json.loads(RETRIEVAL_PATH.read_text(encoding="utf-8"))["tasks"]


class TestEvalLayers:
    @pytest.fixture(scope="class")
    def reports(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("eval")
        runner = EvalRunner(Config(), output_dir=str(out))
        return runner.run_suite("all")

    def test_every_layer_reports_continuous_pass_metrics(self, reports):
        assert set(reports) == {"regression", "context", "memory", "resume", "retrieval"}
        for name, rep in reports.items():
            assert rep["ok"] is True, f"{name}: {rep['summary']}"
            assert rep["total"] > 0
            assert 0.0 <= rep["pass_rate"] <= 1.0
            assert rep["passed"] <= rep["total"]
            assert f"{rep['passed']}/{rep['total']}" in rep["summary"] or name == "context"

    def test_regression_layer(self, reports):
        rep = reports["regression"]
        assert rep["pass_rate"] >= 0.9
        assert rep["total"] >= 15
        assert "含负例/边界" in rep["summary"]

    def test_context_layer(self, reports):
        rep = reports["context"]
        assert rep["pass_rate"] >= 0.9
        assert rep["retention_rate"] == 1.0
        assert all(s["compliance"] == 1.0 for s in rep["stats"])
        assert any(s["folds"] >= 3 for s in rep["stats"])

    def test_memory_layer(self, reports):
        rep = reports["memory"]
        assert rep["pass_rate"] >= 0.9
        for scenario in ("fresh_hit", "stale", "wrong", "missing"):
            assert rep["scenario_stats"].get(scenario, {}).get("total", 0) >= 1
            assert rep["scenario_stats"][scenario]["passed"] == rep["scenario_stats"][scenario]["total"]

    def test_resume_layer(self, reports):
        rep = reports["resume"]
        assert rep["pass_rate"] >= 0.9
        assert rep["drift_accuracy"] >= 0.9
        assert rep["resume_completion"] >= 0.9
        assert any(s["drift_type"] == "large_scale" for s in rep["scenarios"])

    def test_retrieval_layer(self, reports):
        rep = reports["retrieval"]
        assert rep["pass_rate"] >= 0.9
        assert set(rep["type_stats"]) == {"exact", "synonym", "distractor", "empty"}
        assert all(s["passed"] == s["total"] for s in rep["type_stats"].values())
        assert rep["avg_recall"]["hybrid"][3] > rep["avg_recall"]["substring"][3]
        assert rep["mrr"]["hybrid"] > rep["mrr"]["substring"]

    def test_deterministic_repeat(self, tmp_path):
        out1 = tmp_path / "e1"
        out2 = tmp_path / "e2"
        r1 = EvalRunner(Config(), output_dir=str(out1)).run_suite("context")
        r2 = EvalRunner(Config(), output_dir=str(out2)).run_suite("context")
        assert r1["context"]["summary"] == r2["context"]["summary"]
        assert r1["context"]["stats"] == r2["context"]["stats"]

    def test_memory_regression_sensitivity(self, tmp_path):
        cfg = Config()
        cfg.set("memory.enabled", False)
        rep = EvalRunner(cfg, output_dir=str(tmp_path / "memory-off")).run_suite("memory")["memory"]
        assert rep["ok"] is False
        assert rep["pass_rate"] < 0.9

    def test_drift_regression_sensitivity(self, tmp_path):
        cfg = Config()
        cfg.set("checkpoint.detect_drift", False)
        rep = EvalRunner(cfg, output_dir=str(tmp_path / "drift-off")).run_suite("resume")["resume"]
        assert rep["ok"] is False
        assert rep["drift_accuracy"] < 0.9


class TestReportWriting:
    def test_write_report_and_history(self, tmp_path):
        out = tmp_path / "out"
        runner = EvalRunner(Config(), output_dir=str(out))
        reports = runner.run_suite("context")
        runner.write_report(reports)
        assert (out / "report.json").exists()
        assert (out / "report.md").exists()
        history = (out / "eval_history.jsonl").read_text(encoding="utf-8").splitlines()
        assert history
        assert json.loads(history[-1])["layers"]["context"]["pass_rate"] == reports["context"]["pass_rate"]
