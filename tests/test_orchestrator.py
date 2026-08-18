"""Phase 6 — 子代理编排测试(Mock 驱动,零外部依赖)。

验证:
  * Planner 分解出多个子任务;
  * ThreadPoolExecutor 并行执行,子任务互不污染(独立工作区);
  * 聚合正确(total/completed/failed);
  * 部分降级:单个子任务失败不影响其余,汇总标注失败项;
  * 产出 orchestration.json 工件;
  * 默认 planner(无 LLM)退化为单子任务。
"""
from __future__ import annotations

from pathlib import Path

from mycoder.agent.orchestrator import Orchestrator
from mycoder.config import Config


def _mock_factory(sub):
    from mycoder.models import MockBackend
    return MockBackend(script=[{"content": f"完成 {sub.id}"}],
                       default_answer=f"完成 {sub.id}")


def _planner(goal):
    return [{"id": "a", "goal": "子任务A"},
            {"id": "b", "goal": "子任务B"},
            {"id": "c", "goal": "子任务C"}]


def _isolated_config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.set("workspace.root", str(tmp_path / "ws"))
    cfg.set("memory.root", str(tmp_path / "memory"))
    cfg.set("checkpoint.root", str(tmp_path / "checkpoints"))
    cfg.set("artifacts.root", str(tmp_path / "artifacts"))
    return cfg


def test_orchestrate_parallel(tmp_path):
    cfg = _isolated_config(tmp_path)
    orch = Orchestrator(cfg, planner=_planner, backend_factory=_mock_factory, max_workers=3)
    art = orch.run("总目标")
    assert art["summary"]["total"] == 3
    assert art["summary"]["completed"] == 3
    assert art["summary"]["failed"] == 0
    assert set(art["summary"]["final_answers"]) == {"a", "b", "c"}
    # orchestration.json 工件
    p = Path(cfg.get("artifacts.root")) / art["task_id"] / "orchestration.json"
    assert p.exists()
    import json
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["summary"]["completed"] == 3


def test_partial_degradation(tmp_path):
    def factory(sub):
        from mycoder.models import MockBackend
        if sub.id == "b":
            raise RuntimeError("子任务B 故意失败")
        return MockBackend(script=[{"content": "ok"}], default_answer="ok")

    cfg = _isolated_config(tmp_path)
    orch = Orchestrator(cfg, planner=_planner, backend_factory=factory, max_workers=3)
    art = orch.run("目标")
    assert art["summary"]["total"] == 3
    assert art["summary"]["completed"] == 2
    assert art["summary"]["failed"] == 1
    assert art["summary"]["failed_ids"] == ["b"]
    # 失败项不影响成功项的结果
    assert "a" in art["summary"]["final_answers"]
    assert "c" in art["summary"]["final_answers"]
    assert "b" not in art["summary"]["final_answers"]


def test_default_planner_single_subtask(tmp_path):
    cfg = _isolated_config(tmp_path)
    orch = Orchestrator(cfg, backend_factory=_mock_factory)  # 未注入 planner
    art = orch.run("单目标")
    assert art["summary"]["total"] == 1
    assert art["summary"]["completed"] == 1


def test_events_emitted(tmp_path):
    cfg = _isolated_config(tmp_path)
    events = []
    orch = Orchestrator(cfg, planner=_planner, backend_factory=_mock_factory,
                        max_workers=3, on_event=events.append)
    orch.run("目标")
    types = [e["type"] for e in events]
    assert "orchestration_start" in types
    assert types.count("subtask_end") == 3
    assert "orchestration_end" in types
