"""裸模型基线评测(与 Layer 6 同任务集,度量 Harness 的增量价值)。

Layer 6 回答"harness + 真实模型能不能跑通",本模块回答"harness 比不用它好多少":
固定模型与任务集,只改变"有没有框架",跑两条不依赖 harness 的裸基线臂:

  * single_shot —— 裸模型单次调用:把目标与 setup 文件内容一次性放进 prompt,
    要求模型直接输出全部文件(代码块标注 path= 相对路径),由确定性提取器落盘;
    无工具循环、无多轮修正,是 agentless 评测的标准做法。
  * naive_loop  —— 朴素 agent 循环:最简 tool-calling 循环(模型↔工具往返直到终答),
    刻意不复用 harness 的上下文治理/结构化记忆/checkpoint/安全审批链/去重/工件系统,
    只保留 Workspace 文件边界与同一批文件类工具 —— 后者是纯粹的安全约束,
    不属于被评测的"智能"能力。shell_exec/memory_query 依赖 harness 的审批链与
    记忆系统,基线臂不暴露,避免无审批的任意命令执行。
  * harness 参考 —— 若存在 Layer 6 的 real_report.json(output_dir 或
    .mycoder/real/),则在对照表中并排展示,形成三臂对比。

断言与指标与 Layer 6 完全同源:EvalRunner._check_expect 硬断言 + 可选 LLM judge
(同一 LLMJudge 实现,默认不启用),token/成本/耗时按同一口径累计,
保证三臂数字可直接对比。基线臂的低通过率是预期测量结果而非失败,
因此报告的 ok 只表示"测量完成且产生了数据"。
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..config import Config
from ..cost import CostTracker
from ..models import ModelBackend, create_backend
from ..state import Message, RunResult, Step, ToolCall
from ..tools import ToolContext, ToolResult, Workspace, build_registry
from ..util import short_id
from .benchmark import load_benchmarks
from .judge import LLMJudge
from .runner import EvalRunner

# naive_loop 暴露给裸模型的工具:文件类工具足够覆盖 real_tasks.json 的任务,
# shell_exec(高风险审批)与 memory_query(依赖结构化记忆)刻意排除。
_NAIVE_TOOLS: tuple[str, ...] = ("file_read", "file_write", "file_edit",
                                 "file_list", "grep_search")

_SINGLE_SHOT_SYSTEM = (
    "你是一个代码生成引擎,只输出文件内容,不要解释。"
    "对每个需要创建或修改的文件,输出一个代码块,并在代码块语言标注后给出相对路径,格式:\n"
    "```python path=utils.py\n<完整文件内容>\n```\n"
    "未涉及的文件保持原样。除代码块外不要输出任何内容。"
)

_NAIVE_SYSTEM = (
    "你是一个本地编程助手,通过工具调用在工作区内完成任务:"
    "先用 file_read 查看需要的文件,再用 file_write/file_edit 修改,"
    "完成后直接给出文字终答(不再调用工具)。不要操作工作区之外的任何路径。"
)

# 提取 ```lang path=xxx.py 代码块;info 行不含反引号,content 非贪婪到下一组 ```
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)


def _invoke_tool(tool, ctx: ToolContext, params: dict) -> ToolResult:
    """执行工具对象的多态 dispatch 方法(工具业务调用,非数据库操作)。"""
    dispatch = tool.execute
    return dispatch(ctx, **params)


def _parse_block_path(info: str) -> str:
    """从代码块信息行解析相对路径:优先 path=xxx,其次裸的带 . 或 / 的 token。"""
    tokens = info.strip().split()
    for token in tokens:
        if token.startswith("path=") and len(token) > len("path="):
            return token[len("path="):].strip("'\"")
    for token in tokens:
        if ("/" in token or "." in token) and not token.startswith("`"):
            return token
    return ""


def _write_code_blocks(ws: Workspace, text: str) -> list[str]:
    """把模型回复中的 path= 代码块写入工作区(agentless 评测的标准落盘做法)。

    只做确定性文本提取:路径非法/逃逸的块直接跳过,缺失交给硬断言判定。
    """
    written: list[str] = []
    for info, body in _FENCE_RE.findall(text or ""):
        rel = _parse_block_path(info)
        if not rel:
            continue
        try:
            ws.write_text(rel, body)
            written.append(rel)
        except Exception:
            continue
    return written


def _single_shot_user_text(task: dict) -> str:
    parts = [f"任务目标:\n{task.get('goal', '')}"]
    files = task.get("setup_files") or {}
    if files:
        blob = "\n\n".join(f"### {rel}\n```text\n{content}\n```"
                           for rel, content in files.items())
        parts.append(f"工作区现有文件(修改时输出完整新内容):\n{blob}")
    hint = task.get("files_hint") or []
    if hint:
        parts.append("相关文件提示: " + ", ".join(hint))
    parts.append("请输出修改后的完整文件。")
    return "\n\n".join(parts)


def _naive_user_text(task: dict) -> str:
    parts = [f"任务目标:\n{task.get('goal', '')}"]
    hint = task.get("files_hint") or []
    if hint:
        parts.append("相关文件提示: " + ", ".join(hint))
    parts.append("请开始;完成后直接给出终答。")
    return "\n\n".join(parts)


def _parse_arguments(raw: Any) -> dict:
    """解析工具调用参数(兼容 JSON 字符串与 dict 两种来源)。"""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _fmt_verdict(value: bool | None) -> str:
    return "—" if value is None else ("通过" if value else "失败")


class RawBaselineRunner:
    """在同一任务集上运行两条裸基线臂,并(可选)并排 Layer 6 结果形成三臂对照。"""

    ARMS: tuple[str, ...] = ("single_shot", "naive_loop")

    def __init__(self, config: Config, output_dir: str | Path = ".mycoder/real_baseline",
                 tasks_path: str | Path | None = None,
                 backend_factory: Callable[[Config], ModelBackend] | None = None,
                 judge_backend: ModelBackend | None = None):
        self.base_config = config
        self.output_dir = Path(output_dir)
        self.tasks_path = Path(tasks_path or config.get(
            "eval.real_baseline.tasks",
            config.get("eval.real.tasks", "benchmarks/real_tasks.json")))
        self.backend_factory = backend_factory or create_backend
        self.judge_backend = judge_backend
        # 与 harness 相同的步数预算:步数是基线臂被度量的能力之一,不应人为压低
        self.max_steps = int(config.get("eval.real_baseline.max_steps",
                                        config.get("harness.max_steps", 30)))
        self.max_calls_per_turn = int(config.get(
            "eval.real_baseline.max_tool_calls_per_turn",
            config.get("harness.max_tool_calls_per_turn", 8)))

    # ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        if self.base_config.model_backend == "mock" and self.backend_factory is create_backend:
            return {"ok": False, "skipped": True, "passed": 0, "total": 0,
                    "pass_rate": 0.0,
                    "summary": "裸基线评测需要 model.backend=local_openai;当前配置为 mock",
                    "details": [], "results": []}
        tasks = load_benchmarks(self.tasks_path)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = [self._run_task(arm, task) for arm in self.ARMS for task in tasks]

        arms: dict[str, dict[str, Any]] = {}
        for arm in self.ARMS:
            arm_rows = [r for r in rows if r["arm"] == arm]
            passed = sum(int(r["passed"]) for r in arm_rows)
            arms[arm] = {
                "passed": passed, "total": len(arm_rows),
                "pass_rate": round(passed / len(arm_rows), 4) if arm_rows else 0.0,
                "prompt_tokens_total": sum(int(r["metrics"].get("prompt_tokens_total", 0))
                                           for r in arm_rows),
                "completion_tokens_total": sum(int(r["metrics"].get("completion_tokens_total", 0))
                                               for r in arm_rows),
                "cost_usd_total": round(sum(float(r["metrics"].get("cost_usd", 0.0))
                                            for r in arm_rows), 6),
                "elapsed_s_total": round(sum(float(r.get("elapsed_s", 0.0))
                                             for r in arm_rows), 3),
            }
        comparison = self._comparison(rows)
        reference = self._load_harness_reference()

        n = len(tasks)
        summary = (f"裸基线对照: single_shot {arms['single_shot']['passed']}/{n}, "
                   f"naive_loop {arms['naive_loop']['passed']}/{n}")
        if reference:
            summary += (f"(harness 参考 {reference['passed']}/{reference['total']}, "
                        f"来源: {reference['path']})")

        details: list[str] = []
        for arm, agg in arms.items():
            details.append(f"[{arm}] 通过 {agg['passed']}/{agg['total']}, "
                           f"token {agg['prompt_tokens_total']}/{agg['completion_tokens_total']}, "
                           f"成本 ${agg['cost_usd_total']}, 耗时 {agg['elapsed_s_total']}s")
        details.extend(self._format_detail(r) for r in rows)
        for row in comparison:
            details.append(f"三臂对照 {row['task_id']}: "
                           f"single_shot={_fmt_verdict(row['single_shot'])}, "
                           f"naive_loop={_fmt_verdict(row['naive_loop'])}, "
                           f"harness={_fmt_verdict(row['harness'])}")

        report: dict[str, Any] = {
            "ok": bool(rows),
            "passed": sum(int(r["passed"]) for r in rows),
            "total": len(rows),
            "pass_rate": round(sum(int(r["passed"]) for r in rows) / len(rows), 4)
            if rows else 0.0,
            "summary": summary,
            "arms": arms,
            "comparison": comparison,
            "harness_reference": reference or None,
            "details": details,
            "results": rows,
        }
        (self.output_dir / "real_baseline_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report

    # ------------------------------------------------------------------
    def _run_task(self, arm: str, task: dict) -> dict[str, Any]:
        task_id = task["task_id"]
        workdir = self.output_dir / "workspaces" / f"{task_id}_{arm}"
        cfg = Config(self.base_config.to_dict())
        cfg.set("workspace.root", str(workdir / "workspace"))
        cfg.set("safety.hitl_policy", "allow")
        ws = Workspace(str(workdir / "workspace"),
                       bool(cfg.get("workspace.allow_absolute", False)))
        for rel, content in (task.get("setup_files") or {}).items():
            ws.write_text(rel, content)
        start = time.monotonic()
        try:
            if arm == "single_shot":
                outcome = self._arm_single_shot(cfg, ws, task)
            elif arm == "naive_loop":
                outcome = self._arm_naive_loop(cfg, ws, task)
            else:
                raise ValueError(f"未知基线臂: {arm}")
            result = RunResult(
                task_id=task_id, status=outcome["status"],
                final_answer=outcome["final_answer"],
                steps=[Step(index=0, tool_calls=outcome["tool_calls"])],
                metrics=outcome["metrics"])
            assertion_ok, assertion_messages = EvalRunner._check_expect(
                result, SimpleNamespace(workspace=ws), task)
            judge_verdict = (LLMJudge(self.judge_backend).judge(
                task.get("goal", ""), self._snapshot(ws),
                (task.get("judge") or {}).get("rubric", ""))
                if self.judge_backend is not None else None)
            passed = (result.status == "completed" and assertion_ok
                      and (judge_verdict.passed if judge_verdict is not None else True))
            row: dict[str, Any] = {
                "task_id": task_id, "arm": arm, "status": result.status,
                "passed": passed, "assertions_ok": assertion_ok,
                "assertion_messages": assertion_messages,
                "judge": judge_verdict.__dict__ if judge_verdict is not None else None,
                "metrics": outcome["metrics"],
                "elapsed_s": round(time.monotonic() - start, 3),
                "final_answer": result.final_answer,
            }
            row.update(outcome.get("extra") or {})
            return row
        except Exception as exc:
            return {"task_id": task_id, "arm": arm, "status": "error", "passed": False,
                    "assertions_ok": False, "assertion_messages": [str(exc)],
                    "judge": None, "metrics": {},
                    "elapsed_s": round(time.monotonic() - start, 3), "final_answer": ""}

    # ------------------------------------------------------------------
    def _arm_single_shot(self, cfg: Config, ws: Workspace, task: dict) -> dict[str, Any]:
        backend = self.backend_factory(cfg)
        messages = [Message("system", _SINGLE_SHOT_SYSTEM),
                    Message("user", _single_shot_user_text(task))]
        resp = backend.complete(messages)
        p_tokens, c_tokens, cost = self._meter(cfg, backend, resp)
        extracted = _write_code_blocks(ws, resp.content)
        return {
            "status": "completed" if resp.content else "error",
            "final_answer": resp.content,
            "tool_calls": [],
            "metrics": self._metrics(model_calls=1, tool_calls=0, prompt=p_tokens,
                                     completion=c_tokens, cost=cost, calls=[]),
            "extra": {"extracted_files": extracted},
        }

    def _arm_naive_loop(self, cfg: Config, ws: Workspace, task: dict) -> dict[str, Any]:
        backend = self.backend_factory(cfg)
        registry = build_registry()
        tools = [registry.get(name) for name in _NAIVE_TOOLS]
        schemas = [t.as_openai_schema() for t in tools]
        by_name = {t.name: t for t in tools}
        ctx = ToolContext(workspace=ws, memory=None, config=cfg)
        messages: list[Message] = [Message("system", _NAIVE_SYSTEM),
                                   Message("user", _naive_user_text(task))]
        calls_log: list[ToolCall] = []
        model_calls = 0
        prompt_total = completion_total = 0
        cost_total = 0.0
        status, final_answer = "max_steps", ""
        for _ in range(self.max_steps):
            resp = backend.complete(messages, schemas)
            model_calls += 1
            p_tokens, c_tokens, cost = self._meter(cfg, backend, resp)
            prompt_total += p_tokens
            completion_total += c_tokens
            cost_total += cost
            messages.append(Message("assistant", resp.content,
                                    tool_calls=resp.tool_calls or None))
            if not resp.tool_calls:
                final_answer = resp.content
                status = "completed"
                break
            for tc in resp.tool_calls[: self.max_calls_per_turn]:
                call = self._execute_naive_call(tc, by_name, ctx)
                calls_log.append(call)
                messages.append(Message("tool", call.output or "", name=call.name,
                                        tool_call_id=tc.get("id", "")))
        return {
            "status": status, "final_answer": final_answer,
            "tool_calls": calls_log,
            "metrics": self._metrics(model_calls=model_calls, tool_calls=len(calls_log),
                                     prompt=prompt_total, completion=completion_total,
                                     cost=cost_total, calls=calls_log),
            "extra": {"tool_call_names": [c.name for c in calls_log]},
        }

    @staticmethod
    def _execute_naive_call(tc: dict, by_name: dict, ctx: ToolContext) -> ToolCall:
        """裸循环的工具执行:无参数校验/审批/去重(这正是它与 harness 的差异)。"""
        name = tc.get("name", "")
        call = ToolCall(id=tc.get("id", short_id("call_")), name=name,
                        arguments=_parse_arguments(tc.get("arguments", "{}")))
        tool = by_name.get(name)
        if tool is None:
            call.status = "denied"
            call.error = f"未知工具: {name}"
            call.output = f"[已拦截] 未知工具: {name}"
            return call
        try:
            result = _invoke_tool(tool, ctx, call.arguments)
            call.status = "ok" if result.ok else "error"
            call.output = result.output or result.error
            call.error = result.error or None
        except Exception as exc:
            call.status = "error"
            call.error = str(exc)
            call.output = f"[工具异常] {type(exc).__name__}: {exc}"
        return call

    # ------------------------------------------------------------------
    @staticmethod
    def _meter(cfg: Config, backend: ModelBackend, resp) -> tuple[int, int, float]:
        """token/成本计量,与 harness 同口径(usage 优先,成本走同一价目表)。"""
        usage = getattr(resp, "usage", None) or {}
        p_tokens = int(usage.get("prompt_tokens") or 0)
        c_tokens = int(usage.get("completion_tokens") or 0)
        model_name = getattr(backend, "model", "") or "unknown"
        cost = CostTracker.from_config(cfg).cost_of(model_name, p_tokens, c_tokens)
        return p_tokens, c_tokens, cost

    @staticmethod
    def _metrics(model_calls: int, tool_calls: int, prompt: int, completion: int,
                 cost: float, calls: list[ToolCall]) -> dict[str, Any]:
        return {
            "model_calls": model_calls, "steps": model_calls,
            "tool_calls": tool_calls,
            "read_calls": sum(1 for c in calls if c.name == "file_read"),
            "write_calls": sum(1 for c in calls
                               if c.name in ("file_write", "file_edit")),
            "prompt_tokens_total": prompt, "completion_tokens_total": completion,
            "cost_usd": round(cost, 6),
        }

    @staticmethod
    def _snapshot(ws: Workspace) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for rel in ws.list_files():
            try:
                snapshot[rel] = ws.read_text(rel) or ""
            except Exception:
                continue
        return snapshot

    def _load_harness_reference(self) -> dict[str, Any]:
        """尽力加载 Layer 6 报告作为第三臂参考;找不到则不展示。"""
        candidates = [
            self.output_dir / "real_report.json",
            Path(self.base_config.get("eval.real_baseline.harness_report",
                                      ".mycoder/real/real_report.json")),
        ]
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results = data.get("results") or []
                if results:
                    return {"path": str(path),
                            "passed": sum(int(r.get("passed", 0)) for r in results),
                            "total": len(results),
                            "per_task": {r["task_id"]: {
                                "passed": bool(r.get("passed")),
                                "judge_score": (r.get("judge") or {}).get("score"),
                            } for r in results}}
            except Exception:
                continue
        return {}

    def _comparison(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_task: dict[str, dict[str, bool]] = {}
        for r in rows:
            by_task.setdefault(r["task_id"], {})[r["arm"]] = bool(r["passed"])
        reference = self._load_harness_reference().get("per_task", {})
        out: list[dict[str, Any]] = []
        for task_id, arms_map in sorted(by_task.items()):
            ref = reference.get(task_id)
            out.append({"task_id": task_id,
                        "single_shot": arms_map.get("single_shot"),
                        "naive_loop": arms_map.get("naive_loop"),
                        "harness": ref.get("passed") if ref else None})
        return out

    @staticmethod
    def _format_detail(row: dict[str, Any]) -> str:
        metrics = row.get("metrics") or {}
        return (f"{row['task_id']}[{row['arm']}]: {'通过' if row['passed'] else '失败'}, "
                f"状态={row.get('status')},断言={'通过' if row.get('assertions_ok') else '失败'}, "
                f"模型调用={metrics.get('model_calls', 0)},"
                f"token={metrics.get('prompt_tokens_total', 0)}"
                f"/{metrics.get('completion_tokens_total', 0)},"
                f"耗时={row.get('elapsed_s', 0)}s")
