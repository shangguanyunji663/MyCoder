"""真实模型端到端任务评测(Layer 6)。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..agent import AgentHarness
from ..config import Config
from ..models import ModelBackend, create_backend
from ..safety import AllowAllProvider
from ..state import TaskInput
from .benchmark import load_benchmarks
from .judge import LLMJudge
from .runner import EvalRunner


class RealTaskRunner:
    """在独立工作区运行真实模型任务,同时记录硬断言和 LLM 评委结果。"""

    def __init__(self, config: Config, output_dir: str | Path = ".mycoder/real",
                 tasks_path: str | Path | None = None,
                 backend_factory: Callable[[Config], ModelBackend] | None = None,
                 judge_backend: ModelBackend | None = None):
        self.base_config = config
        self.output_dir = Path(output_dir)
        self.tasks_path = Path(tasks_path or config.get("eval.real.tasks", "benchmarks/real_tasks.json"))
        self.backend_factory = backend_factory or create_backend
        self.judge_backend = judge_backend

    def run(self) -> dict[str, Any]:
        if self.base_config.model_backend == "mock" and self.backend_factory is create_backend:
            return {"ok": False, "skipped": True, "passed": 0, "total": 0,
                    "pass_rate": 0.0,
                    "summary": "真实评测需要 model.backend=local_openai;当前配置为 mock",
                    "details": [], "results": []}
        tasks = load_benchmarks(self.tasks_path)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = [self._run_one(task) for task in tasks]
        passed = sum(int(r["passed"]) for r in results)
        total = len(results)
        rate = passed / total if total else 0.0
        threshold = float(self.base_config.get("eval.real.pass_threshold", 0.5))
        prompt_total = sum(int((r.get("metrics") or {}).get("prompt_tokens_total", 0)) for r in results)
        completion_total = sum(
            int((r.get("metrics") or {}).get("completion_tokens_total", 0)) for r in results
        )
        cost_total = sum(float((r.get("metrics") or {}).get("cost_usd", 0.0)) for r in results)
        elapsed_total = sum(float(r.get("elapsed_s", 0.0)) for r in results)
        report = {
            "ok": bool(total) and rate >= threshold,
            "passed": passed, "total": total, "pass_rate": round(rate, 4),
            "threshold": threshold,
            "prompt_tokens_total": prompt_total,
            "completion_tokens_total": completion_total,
            "cost_usd_total": round(cost_total, 6),
            "elapsed_s_total": round(elapsed_total, 3),
            "summary": f"真实模型任务 {passed}/{total} 通过(pass_rate={rate:.0%})",
            "details": [self._format_detail(r) for r in results],
            "results": results,
        }
        (self.output_dir / "real_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report

    def _run_one(self, task: dict) -> dict[str, Any]:
        task_id = task["task_id"]
        workdir = self.output_dir / "workspaces" / task_id
        cfg = Config(self.base_config.to_dict())
        cfg.set("workspace.root", str(workdir / "workspace"))
        cfg.set("memory.root", str(workdir / "memory"))
        cfg.set("checkpoint.root", str(workdir / "checkpoints"))
        cfg.set("artifacts.root", str(workdir / "artifacts"))
        cfg.set("safety.hitl_policy", "allow")
        start = time.monotonic()
        result: Any = None
        assertion_ok = False
        assertion_messages: list[str] = []
        judge_verdict = None
        try:
            backend = self.backend_factory(cfg)
            harness = AgentHarness.build(cfg, backend=backend, approver=AllowAllProvider())
            for rel, content in (task.get("setup_files") or {}).items():
                harness.workspace.write_text(rel, content)
            result = harness.run(TaskInput(task_id=task_id, goal=task.get("goal", ""),
                                           files_hint=task.get("files_hint", [])))
            assertion_ok, assertion_messages = EvalRunner._check_expect(result, harness, task)
            snapshot = {}
            for rel in harness.workspace.list_files():
                try:
                    snapshot[rel] = harness.workspace.read_text(rel) or ""
                except Exception:
                    continue
            if self.judge_backend is not None:
                jbackend = self.judge_backend
            else:
                judge_cfg = Config(cfg.to_dict())
                judge_timeout = int(self.base_config.get(
                    "eval.real.judge_timeout_seconds", 60))
                judge_cfg.set("model.local_openai.timeout_seconds", judge_timeout)
                judge_overrides = self.base_config.get("eval.real.judge", {}) or {}
                for key in ("base_url", "api_key", "model"):
                    value = judge_overrides.get(key)
                    if value:
                        judge_cfg.set(f"model.local_openai.{key}", value)
                jbackend = self.backend_factory(judge_cfg)
            judge_verdict = LLMJudge(jbackend).judge(
                task.get("goal", ""), snapshot, (task.get("judge") or {}).get("rubric", ""))
            metrics = dict(result.metrics or {})
            passed = result.status == "completed" and assertion_ok and judge_verdict.passed
            return {
                "task_id": task_id, "status": result.status, "passed": passed,
                "assertions_ok": assertion_ok, "assertion_messages": assertion_messages,
                "judge": judge_verdict.__dict__, "metrics": metrics,
                "elapsed_s": round(time.monotonic() - start, 3),
                "final_answer": result.final_answer,
            }
        except Exception as exc:
            return {"task_id": task_id, "status": "error", "passed": False,
                    "assertions_ok": False, "assertion_messages": [str(exc)],
                    "judge": None, "metrics": {},
                    "elapsed_s": round(time.monotonic() - start, 3), "final_answer": ""}

    @staticmethod
    def _format_detail(row: dict[str, Any]) -> str:
        judge = row.get("judge") or {}
        return (f"{row['task_id']}: {'通过' if row['passed'] else '失败'}, "
                f"状态={row.get('status')},断言={'通过' if row.get('assertions_ok') else '失败'}, "
                f"judge={judge.get('score', 0)}/5,耗时={row.get('elapsed_s', 0)}s")
