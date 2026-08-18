"""子代理编排(可选增强,默认关闭)。

把复杂目标交给 Planner 分解为若干子任务,每个子任务由一个独立的子 AgentHarness
并行执行(ThreadPoolExecutor),最后聚合结果。核心特性:
  * 并行:子任务在独立工作区并行跑,互不污染;
  * 部分降级:单个子任务失败不影响其余,汇总时标注失败项;
  * 工件:产出 orchestration.json,记录分解与执行轨迹;
  * 可观测:通过 on_event 发出 orchestration_start / subtask_end / orchestration_end。

Planner 默认是确定性退化分解(整体当一个子任务);生产环境可注入 LLM planner
(返回子任务 JSON)获得真正的智能分解 —— 核心零依赖不受影响。
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import Config
from ..state import TaskInput


@dataclass
class SubTask:
    id: str
    goal: str
    status: str = "pending"          # pending | running | completed | failed
    result: dict | None = None
    error: str | None = None


def _default_planner(goal: str) -> list[dict]:
    """确定性退化分解:未提供 LLM planner 时,把目标整体作为一个子任务。"""
    return [{"id": "sub-1", "goal": goal}]


class Orchestrator:
    """把目标分解为子任务并并行编排执行。"""

    def __init__(self, config: Config, planner: Callable[[str], list[dict]] | None = None,
                 backend_factory: Callable[[SubTask], object] | None = None,
                 max_workers: int | None = None, on_event: Callable[[dict], None] | None = None):
        self.config = config
        self.planner = planner or _default_planner
        self.backend_factory = backend_factory
        self.max_workers = max_workers or int(config.get("agent.orchestrator.max_workers", 4))
        self.on_event = on_event

    # ------------------------------------------------------------------
    def decompose(self, goal: str) -> list[SubTask]:
        plan = self.planner(goal)
        subs: list[SubTask] = []
        for i, p in enumerate(plan):
            subs.append(SubTask(id=str(p.get("id") or f"sub-{i + 1}"),
                                goal=str(p.get("goal") or p)))
        return subs

    def run(self, goal: str, task_id: str | None = None) -> dict:
        task_id = task_id or ("orch-" + uuid.uuid4().hex[:8])
        subs = self.decompose(goal)
        self._emit({"type": "orchestration_start", "task_id": task_id,
                    "subtasks": [s.id for s in subs]})

        def _run_one(sub: SubTask) -> SubTask:
            sub.status = "running"
            try:
                backend = self.backend_factory(sub) if self.backend_factory else None
                harness = self._build_harness(sub, backend)
                res = harness.run(TaskInput(task_id=f"{task_id}/{sub.id}", goal=sub.goal))
                sub.status = "completed"
                sub.result = {"status": res.status, "final_answer": res.final_answer}
            except Exception as exc:  # 部分降级:单子任务失败不影响其余
                sub.status = "failed"
                sub.error = str(exc)
            return sub

        results: dict[str, SubTask] = {}
        workers = max(1, min(self.max_workers, len(subs)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_run_one, s): s for s in subs}
            for fut in as_completed(futs):
                sub = fut.result()
                results[sub.id] = sub
                self._emit({"type": "subtask_end", "task_id": task_id,
                            "sub": sub.id, "status": sub.status})

        summary = self.aggregate(list(results.values()))
        artifact = {
            "task_id": task_id, "goal": goal,
            "subtasks": [vars(s) for s in subs], "summary": summary,
        }
        self._export(artifact)
        self._emit({"type": "orchestration_end", "task_id": task_id, "summary": summary})
        return artifact

    # ------------------------------------------------------------------
    @staticmethod
    def aggregate(subs: list[SubTask]) -> dict:
        completed = [s for s in subs if s.status == "completed"]
        failed = [s for s in subs if s.status == "failed"]
        return {"total": len(subs), "completed": len(completed), "failed": len(failed),
                "failed_ids": [s.id for s in failed],
                "final_answers": {s.id: (s.result or {}).get("final_answer")
                                  for s in completed}}

    def _build_harness(self, sub: SubTask, backend):
        from ..agent import AgentHarness
        from ..safety import AllowAllProvider
        cfg = Config(self.config.to_dict())
        # 每子任务完全独立的工作区 / 记忆 / 断点 / 工件根,避免并行时相互污染
        base = Path(self.config.get("workspace.root", "."))
        sub_dir = base / f".orch_{sub.id}"
        cfg.set("workspace.root", str(sub_dir / "ws"))
        cfg.set("memory.root", str(sub_dir / "memory"))
        cfg.set("checkpoint.root", str(sub_dir / "checkpoints"))
        cfg.set("artifacts.root", str(sub_dir / "artifacts"))
        cfg.set("observability.enabled", False)
        return AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())

    def _export(self, artifact: dict) -> None:
        root = Path(self.config.get("artifacts.root", ".mycoder/artifacts")) / artifact["task_id"]
        root.mkdir(parents=True, exist_ok=True)
        (root / "orchestration.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")

    def _emit(self, event: dict) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:
            pass
