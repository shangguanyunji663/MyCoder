"""Agent Harness 主调度循环。

这是整个项目的中枢:把 模型后端 / 工具 / 上下文治理 / 记忆 / checkpoint /
安全边界 / 运行工件 统一编排成一个可中断、可恢复、可复盘的主循环:

    ┌─────────────────────────────────────────────────────────────┐
    │  loop:                                                       │
    │   1. context.assemble()  组织并裁剪上下文(预算治理)          │
    │   2. backend.complete()  调用模型(mock 或本地 OpenAI 兼容)   │
    │   3. 有工具调用? -> safety.check() -> 执行 -> 记忆沉淀        │
    │      无工具调用? -> 终答,结束                                  │
    │   4. 记录轨迹 + 累计指标 + 周期性/裁剪前 checkpoint            │
    └─────────────────────────────────────────────────────────────┘

主循环本身不关心模型是不是真的"聪明",它只保证:确定性、可观测、可恢复。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, ClassVar

from ..artifacts import ArtifactManager, Metrics, RunRecorder
from ..checkpoint import CheckpointStore, DriftReport, WorkspaceDriftDetector
from ..config import Config
from ..context import ContextManager, PruneInfo
from ..cost import CostTracker
from ..memory import StructuredMemory
from ..memory.vectors import HashingEmbedder
from ..models import ModelBackend
from ..safety import Redactor, SafetyGuard
from ..state import Message, RunResult, Step, TaskInput, ToolCall
from ..tools import ToolContext, ToolRegistry, Workspace
from ..util import now_iso, short_id


# --------------------------------------------------------------------------
# 消息/轮次 序列化(供 checkpoint 使用)
# --------------------------------------------------------------------------
def _msg_to_dict(m: Message) -> dict:
    return {"role": m.role, "content": m.content, "name": m.name,
            "tool_call_id": m.tool_call_id, "tool_calls": m.tool_calls, "meta": m.meta}


def _msg_from_dict(d: dict) -> Message:
    return Message(role=d.get("role", "assistant"), content=d.get("content", ""),
                   name=d.get("name"), tool_call_id=d.get("tool_call_id"),
                   tool_calls=d.get("tool_calls"), meta=d.get("meta", {}))


def _turn_to_dict(t: dict) -> dict:
    return {"assistant": _msg_to_dict(t["assistant"]),
            "tool": [_msg_to_dict(m) for m in t["tool"]]}


def _turn_from_dict(t: dict) -> dict:
    return {"assistant": _msg_from_dict(t["assistant"]),
            "tool": [_msg_from_dict(m) for m in t["tool"]]}


def _metrics_restore(snap: dict) -> Metrics:
    m = Metrics()
    for f in ("steps", "tool_calls", "read_calls", "read_cache_hits", "write_calls",
              "prompt_tokens_total", "completion_tokens_total", "cost_usd",
              "latency_ms_total", "prunes",
              "files_remembered", "memory_queries", "denied_actions", "skipped_repeats"):
        if f in snap:
            setattr(m, f, snap[f])
    m.compression_ratios = list(snap.get("compression_ratios", []))
    return m


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式(逐行 JSON,可被 json.loads 解析)。"""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def get_logger(config: Config) -> logging.Logger:
    logger = logging.getLogger("mycoder")
    logger.setLevel(config.get("logging.level", "INFO"))
    if not logger.handlers:
        fmt_mode = config.get("logging.format", "text")
        if fmt_mode == "json":
            formatter: logging.Formatter = JsonFormatter()
        else:
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        if config.get("logging.file"):
            fh = logging.FileHandler(config.get("logging.file"), encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        if config.get("logging.console", True):  # 同时输出控制台,便于本地观察
            import sys
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(formatter if fmt_mode == "json" else
                            logging.Formatter("[%(levelname)s] %(message)s"))
            logger.addHandler(sh)
        logger.propagate = False
    return logger


class AgentHarness:
    # 参与记忆沉淀 & 统计的文件写类工具
    _FILE_TOOLS: ClassVar[set[str]] = {"file_read", "file_write", "file_edit"}

    def __init__(self, config: Config, backend: ModelBackend, workspace: Workspace,
                 registry: ToolRegistry, memory: StructuredMemory | None = None,
                 guard: SafetyGuard | None = None, checkpoint: CheckpointStore | None = None,
                 artifacts: ArtifactManager | None = None, redactor: Redactor | None = None,
                 summarizer=None, on_event=None):
        self.config = config
        self.backend = backend
        self.workspace = workspace
        self.registry = registry
        self.memory = memory
        self.redactor = redactor or Redactor(enabled=False)
        # on_event:最小侵入的事件总线(可观测性 Tracer / API SSE EventBus 都接这里)
        self.on_event = on_event
        self.checkpoint = checkpoint or CheckpointStore(config.get("checkpoint.root", ".mycoder/checkpoints"),
                                                        enabled=False)
        self.artifacts = artifacts or ArtifactManager(config.get("artifacts.root", ".mycoder/artifacts"),
                                                      config, redactor=self.redactor)
        self.guard = guard or SafetyGuard(config, workspace, redactor=self.redactor)
        self.context = ContextManager(config, summarizer=summarizer)
        self.cost_tracker = CostTracker.from_config(config)
        self.logger = get_logger(config)
        self.metrics = Metrics()
        self.current_task_id: str | None = None

    # ------------------------------------------------------------------
    # 装配工厂
    @classmethod
    def build(cls, config: Config, backend: ModelBackend | None = None,
              workspace_root: str | None = None, memory_root: str | None = None,
              approver=None, on_event=None) -> AgentHarness:
        from ..models import create_backend
        backend = backend or create_backend(config)
        ws_root = workspace_root or config.get("workspace.root", ".")
        ws = Workspace(ws_root, config.get("workspace.allow_absolute", False))
        from ..tools import build_registry
        registry = build_registry()
        memory = StructuredMemory(memory_root or config.get("memory.root", ".mycoder/memory"),
                                  enabled=config.get("memory.enabled", True),
                                  retrieval_mode=config.get("memory.retrieval.mode", "substring"),
                                  hybrid_alpha=float(config.get("memory.retrieval.alpha", 0.5)),
                                  embedder=_make_embedder(config))

        redactor = Redactor(enabled=config.get("safety.redaction_enabled", True))
        guard = SafetyGuard(config, ws, approver=approver, redactor=redactor)
        cp = CheckpointStore(config.get("checkpoint.root", ".mycoder/checkpoints"),
                             enabled=config.get("checkpoint.enabled", True))
        am = ArtifactManager(config.get("artifacts.root", ".mycoder/artifacts"),
                             config, redactor=redactor)
        # 摘要器:llm 模式复用主后端压缩折叠历史(失败自动回退确定性)
        summarizer = None
        if config.get("context.summarizer") == "llm":
            from ..context.summarizer import LLMSummarizer
            summarizer = LLMSummarizer(backend=backend)
        # 可观测性:Tracer 作为默认 on_event 消费者(零依赖,导出 trace.json);
        # 若调用方传入自己的 on_event(API SSE EventBus),则两者都收到事件。
        tracer = None
        if config.get("observability.enabled", True):
            from ..observability import Tracer
            tracer = Tracer(artifacts_root=config.get("artifacts.root", ".mycoder/artifacts"),
                            enabled=True)
        harness = cls(config, backend, ws, registry, memory, guard, cp, am, redactor,
                      summarizer=summarizer, on_event=on_event)

        def _dispatch(event: dict) -> None:
            if tracer is not None:
                tracer.handle(event)
            if on_event is not None:
                on_event(event)

        harness.on_event = _dispatch
        return harness

    # ------------------------------------------------------------------
    def _emit(self, event: dict) -> None:
        """把语义事件发给 on_event 消费者(可观测性 Tracer / SSE EventBus)。

        埋点绝不能拖垮主链路:任何异常都被吞掉。
        """
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def run(self, task: TaskInput, stop_after_steps: int | None = None) -> RunResult:
        return self._run(task, start_step=0, metrics=Metrics(), stop_after_steps=stop_after_steps,
                         drift=None, reason="run")

    def resume(self, task_id: str, stop_after_steps: int | None = None) -> RunResult:
        cp = self.checkpoint.load(task_id)
        if cp is None:
            return RunResult(task_id, status="error", error=f"找不到断点: {task_id}")
        # 1) 工作区漂移识别
        drift: DriftReport | None = None
        if self.config.get("checkpoint.detect_drift", True):
            before = cp.get("workspace_fingerprint", {})
            after = self.workspace.snapshot()
            drift = WorkspaceDriftDetector.compare(before, after)
            self.logger.info("恢复 %s: %s", task_id, drift.summary())
        # 2) 恢复上下文
        ctx = cp.get("context", {})
        self.backend.load_state(cp.get("backend_state", {}))
        self.context.set_task(ctx.get("goal", ""), ctx.get("files_hint", []),
                              ctx.get("memory_block", ""))
        self.context.raw_turns = [_turn_from_dict(t) for t in ctx.get("raw_turns", [])]
        if ctx.get("last_prune"):
            self.context.last_prune = PruneInfo(
                before_tokens=ctx["last_prune"].get("before_tokens", 0),
                after_tokens=ctx["last_prune"].get("after_tokens", 0),
                pruned=ctx["last_prune"].get("pruned", False),
                strategies=ctx["last_prune"].get("strategies", []))
        task = TaskInput(task_id=cp["task_id"], goal=cp.get("task", {}).get("goal", ""),
                         files_hint=cp.get("task", {}).get("files_hint", []),
                         follow_up_of=cp.get("task", {}).get("follow_up_of"),
                         extra=cp.get("task", {}).get("extra", {}))
        metrics = _metrics_restore(cp.get("metrics", {}))
        drift_dict = None if drift is None else {
            "modified": drift.modified, "added": drift.added, "deleted": drift.deleted,
            "is_drift": drift.is_drift, "summary": drift.summary(),
        }
        return self._run(task, start_step=cp.get("step_index", 0), metrics=metrics,
                         stop_after_steps=stop_after_steps, drift=drift_dict, reason="resume")

    # ------------------------------------------------------------------
    def _run(self, task: TaskInput, start_step: int, metrics: Metrics,
             stop_after_steps: int | None, drift: dict | None, reason: str) -> RunResult:
        self.current_task_id = task.task_id
        self.metrics = metrics
        task_dir = self.artifacts.task_dir(task.task_id)
        recorder = RunRecorder(task_dir / "trajectory.jsonl", redactor=self.redactor)

        # follow-up 记忆注入:让后续任务直接拿到父任务的摘要,避免重读文件
        mem_block = ""
        if task.follow_up_of and self.memory is not None and \
                self.config.get("memory.followup_inject_summaries", True):
            mem_block = self.memory.followup_context(task_id=task.task_id,
                                                     parent_task_id=task.follow_up_of)
        self.context.set_task(task.goal, task.files_hint, mem_block)
        self._checkpoint(task, start_step, reason=reason)

        recorder.record({"type": "task_start", "task_id": task.task_id, "ts": now_iso(),
                         "follow_up_of": task.follow_up_of, "reason": reason})
        self._emit({"type": "task_start", "task_id": task.task_id, "ts": now_iso(),
                    "follow_up_of": task.follow_up_of, "reason": reason})

        max_steps = int(self.config.get("harness.max_steps", 30))
        status, final_answer, error = "completed", "", None
        steps: list[Step] = []

        try:
            for step_idx in range(start_step, max_steps):
                if stop_after_steps is not None and step_idx - start_step >= stop_after_steps:
                    status = "interrupted"
                    self._checkpoint(task, step_idx, reason="interrupt")
                    recorder.record({"type": "interrupt", "step": step_idx, "ts": now_iso()})
                    break

                # 1) 组装 + 裁剪上下文
                messages = self.context.assemble()
                self._emit({"type": "step_start", "index": step_idx, "ts": now_iso()})
                # 2) 调用模型
                t0 = time.time()
                resp = self.backend.complete(messages, self.registry.schemas())
                latency_ms = int((time.time() - t0) * 1000)

                # 2b) 计量:真实 usage(若后端提供)+ 延迟;后端未提供时 completion 用 0 占位
                usage = getattr(resp, "usage", None) or {}
                p_tokens = int(usage.get("prompt_tokens") or self.context.last_prune.after_tokens)
                c_tokens = int(usage.get("completion_tokens") or 0)
                model_name = getattr(self.backend, "model", "") or "unknown"
                step_cost = self.cost_tracker.cost_of(model_name, p_tokens, c_tokens)
                self._emit({"type": "model_call", "index": step_idx, "model": model_name,
                            "prompt_tokens": p_tokens, "completion_tokens": c_tokens,
                            "latency_ms": latency_ms, "ts": now_iso()})

                assistant = Message("assistant", resp.content,
                                    tool_calls=resp.tool_calls or None)

                # 3) 终答判断
                if not resp.tool_calls:
                    final_answer = resp.content
                    self.context.append_turn(assistant, [])
                    self._emit({"type": "step_end", "index": step_idx, "ts": now_iso()})
                    steps.append(Step(index=step_idx, assistant=assistant,
                                      prompt_tokens=p_tokens,
                                      prompt_before_tokens=self.context.last_prune.before_tokens,
                                      completion_tokens=c_tokens,
                                      pruned=self.context.last_prune.pruned,
                                      prune_strategies=self.context.last_prune.strategies,
                                      latency_ms=latency_ms))
                    self.metrics.steps += 1
                    self.metrics.prompt_tokens_total += p_tokens
                    self.metrics.completion_tokens_total += c_tokens
                    self.metrics.latency_ms_total += latency_ms
                    self.metrics.cost_usd += step_cost
                    recorder.record({"type": "step", "index": step_idx,
                                     "assistant": _msg_to_dict(assistant),
                                     "tool_calls": [], "latency_ms": latency_ms,
                                     "prompt_tokens": p_tokens, "completion_tokens": c_tokens,
                                     "ts": now_iso()})
                    break

                # 4) 执行工具
                calls, tool_msgs = self._execute_tools(resp.tool_calls, step_index=step_idx)
                self.context.append_turn(assistant, tool_msgs)

                step = Step(index=step_idx, assistant=assistant, tool_calls=calls,
                            prompt_tokens=p_tokens,
                            prompt_before_tokens=self.context.last_prune.before_tokens,
                            completion_tokens=c_tokens,
                            pruned=self.context.last_prune.pruned,
                            prune_strategies=self.context.last_prune.strategies,
                            latency_ms=latency_ms)
                steps.append(step)
                self._record_step(recorder, step)
                self._emit({"type": "step_end", "index": step_idx, "ts": now_iso()})

                # 5) 指标 & checkpoint
                self.metrics.steps += 1
                self.metrics.prompt_tokens_total += p_tokens
                self.metrics.completion_tokens_total += c_tokens
                self.metrics.latency_ms_total += latency_ms
                self.metrics.cost_usd += step_cost
                if self.context.last_prune.pruned:
                    self.metrics.prunes += 1
                    self.metrics.compression_ratios.append(self.context.last_prune.ratio)
                    if self.config.get("checkpoint.on_prune", True):
                        self._checkpoint(task, step_idx + 1, reason="prune")
                interval = int(self.config.get("checkpoint.interval_steps", 4))
                if self.config.get("checkpoint.enabled", True) and \
                        (step_idx + 1 - start_step) % interval == 0:
                    self._checkpoint(task, step_idx + 1, reason="interval")
            else:
                status = "max_steps"
                recorder.record({"type": "max_steps", "ts": now_iso()})
        except Exception as e:
            status = "error"
            error = f"{type(e).__name__}: {e}"
            self.logger.exception("任务 %s 异常", task.task_id)
            self._checkpoint(task, len(steps), reason="error")
            recorder.record({"type": "error", "error": error, "ts": now_iso()})

        # 收尾:终局 checkpoint + 记忆任务摘要 + 导出工件
        if status not in ("interrupted", "error"):
            self._checkpoint(task, len(steps), reason="final")
        self._remember_task(task, status, final_answer)
        self._sync_guard_metrics()
        result_payload = {"status": status, "final_answer": final_answer, "error": error}
        self.artifacts.export(task.task_id, self.metrics, result_payload,
                              checkpoint_obj=self.checkpoint.load(task.task_id))
        recorder.record({"type": "task_end", "status": status, "ts": now_iso()})
        self._emit({"type": "task_end", "status": status, "ts": now_iso()})
        return RunResult(task_id=task.task_id, status=status, final_answer=final_answer,
                         steps=steps, metrics=self.metrics.snapshot(), drift=drift, error=error)

    # ------------------------------------------------------------------
    def _execute_tools(self, raw_calls: list[dict], step_index: int | None = None
                       ) -> tuple[list[ToolCall], list[Message]]:
        """执行一轮工具调用:安全链 -> 执行 -> 脱敏 -> 记忆沉淀。"""
        calls: list[ToolCall] = []
        tool_msgs: list[Message] = []
        max_calls = int(self.config.get("harness.max_tool_calls_per_turn", 8))
        ctx = ToolContext(workspace=self.workspace, memory=self.memory, config=self.config)

        for tc in raw_calls[:max_calls]:
            name = tc.get("name", "")
            raw_args = tc.get("arguments", "{}")
            # 解析 arguments：支持 JSON 字符串或字典格式
            if isinstance(raw_args, str):
                try:
                    params = json.loads(raw_args)
                except json.JSONDecodeError:
                    params = {}
            elif isinstance(raw_args, dict):
                params = raw_args
            else:
                params = {}
            call = ToolCall(id=tc.get("id", short_id("call_")), name=name, arguments=params)

            tool = self.registry.get(name) if self.registry.has(name) else None
            if tool is None:
                call.status = "denied"
                call.error = f"未知工具: {name}"
                output = f"[已拦截] 未知工具: {name}"
            else:
                t0 = time.time()
                output, meta = self._run_one_tool(tool, params, ctx)
                tool_latency = int((time.time() - t0) * 1000)
                call.status = meta.get("status", "ok")
                call.error = meta.get("error")
                call.output = output
                call.meta = meta
                self._emit({"type": "tool_call", "step_index": step_index,
                            "name": name, "status": call.status,
                            "latency_ms": tool_latency, "ts": now_iso()})
            calls.append(call)
            tool_msgs.append(Message("tool", output, name=name, tool_call_id=tc.get("id", "")))
        return calls, tool_msgs

    def _run_one_tool(self, tool, params: dict, ctx: ToolContext) -> tuple[str, dict]:
        """单次工具调用的安全链 + 执行。返回 (输出文本, meta)。"""
        meta: dict[str, Any] = {}
        gr = self.guard.check(tool, params)
        if not gr.allowed:
            meta.update(status="denied", error=gr.reason)
            return f"[已拦截] {gr.reason}", meta
        if gr.needs_approval:
            if not self.guard.approve(gr.action):
                meta.update(status="denied", error="人工审批未通过")
                return "[已拦截] 人工审批未通过(高风险操作)", meta
            meta["hitl_approved"] = True
        # 去重短路
        if gr.cached_output is not None:
            meta.update(status="ok", cache_hit=True, reason=gr.reason)
            return gr.cached_output, meta
        # 真正的执行
        try:
            result = tool.execute(ctx, **params)
            output = result.output if result.output else result.error
            meta.update(status="ok" if result.ok else "error",
                        error=(result.error or None), **result.meta)
            if result.ok:
                self.guard.record_executed(tool, params, output)
                self._after_tool(tool.name, result.meta)
        except Exception as e:
            meta.update(status="error", error=str(e))
            output = f"[工具异常] {type(e).__name__}: {e}"
        # 脱敏(输出进上下文前)
        return self.redactor.redact(output), meta

    def _after_tool(self, name: str, tool_meta: dict) -> None:
        """工具执行成功后的善后:统计 + 文件摘要沉淀。"""
        self.metrics.tool_calls += 1
        if name == "file_write" or name == "file_edit":
            self.metrics.write_calls += 1
        elif name == "file_read":
            self.metrics.read_calls += 1
        elif name == "memory_query":
            self.metrics.memory_queries += 1
        # 记忆:自动沉淀文件摘要(读/写/改之后)
        if name in self._FILE_TOOLS and self.memory is not None and \
                self.config.get("memory.auto_remember_files", True):
            path = tool_meta.get("path")
            if path:
                try:
                    content = self.workspace.read_text(path) or ""
                    digest = tool_meta.get("file_hash")
                    updated, _ = self.memory.remember_file(
                        path=path, content=content, sha256=digest or "",
                        task_id=self.current_task_id)
                    if updated:
                        self.metrics.files_remembered += 1
                except Exception:
                    pass

    # ------------------------------------------------------------------
    def _checkpoint(self, task: TaskInput, step: int, reason: str) -> None:
        if not self.config.get("checkpoint.enabled", True):
            return
        snap = {
            "version": 1,
            "task_id": task.task_id,
            "reason": reason,
            "step_index": step,
            "backend_state": self.backend.state(),
            "task": {"goal": task.goal, "files_hint": task.files_hint,
                     "follow_up_of": task.follow_up_of, "extra": task.extra},
            "context": {
                "goal": self.context.goal,
                "files_hint": self.context.files_hint,
                "memory_block": self.context.memory_block,
                "raw_turns": [_turn_to_dict(t) for t in self.context.raw_turns],
                "last_prune": {"before_tokens": self.context.last_prune.before_tokens,
                               "after_tokens": self.context.last_prune.after_tokens,
                               "pruned": self.context.last_prune.pruned,
                               "strategies": self.context.last_prune.strategies},
            },
            "workspace_fingerprint": self.workspace.snapshot(),
            "metrics": self.metrics.snapshot(),
        }
        self.checkpoint.save(task.task_id, snap)
        self.logger.info("checkpoint: task=%s step=%s reason=%s", task.task_id, step, reason)
        self._emit({"type": "checkpoint", "step": step, "reason": reason,
                    "task_id": task.task_id, "ts": now_iso()})

    def _remember_task(self, task: TaskInput, status: str, answer: str) -> None:
        if self.memory is None:
            return
        self.memory.remember_task(
            task_id=task.task_id, goal=task.goal, status=status,
            summary=(answer or "")[:500], files=self.context.files_hint,
            parent_task_id=task.follow_up_of)
        self.memory.save()

    def _sync_guard_metrics(self) -> None:
        self.metrics.read_cache_hits = self.guard.read_cache_hits
        self.metrics.skipped_repeats = self.guard.skipped_repeats
        self.metrics.denied_actions = self.guard.denied

    def _record_step(self, recorder: RunRecorder, step: Step) -> None:
        recorder.record({
            "type": "step", "index": step.index,
            "assistant": _msg_to_dict(step.assistant) if step.assistant else {},
            "tool_calls": [{
                "id": c.id, "name": c.name, "arguments": c.arguments,
                "status": c.status, "error": c.error, "meta": c.meta,
            } for c in step.tool_calls],
            "prompt_tokens": step.prompt_tokens,
            "prompt_before_tokens": step.prompt_before_tokens,
            "completion_tokens": step.completion_tokens,
            "pruned": step.pruned,
            "prune_strategies": step.prune_strategies,
            "latency_ms": step.latency_ms,
            "ts": now_iso(),
        })


def _make_embedder(config) -> HashingEmbedder:
    """按配置选择嵌入器:默认 hashing(零依赖),可选 fastembed(懒加载)。"""
    kind = config.get("memory.retrieval.embedder", "hashing")
    if kind == "fastembed":
        from ..memory.vectors import FastEmbedEmbedder
        return FastEmbedEmbedder()
    return HashingEmbedder()
