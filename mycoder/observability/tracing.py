"""轻量级链路追踪(可观测性)。

设计目标:
  * 零依赖:核心 Span/Tracer 仅用标准库,任何环境都能跑(离线 CI 友好);
  * OTLP 风格:导出 trace.json 的 span 结构与 OpenTelemetry 的
    {trace_id, span_id, parent_span_id, name, start, end, duration_ms,
     status, attributes, events} 对齐,便于日后接入真正的 OTLP 收集器;
  * 可选桥接:检测到 `opentelemetry-api` 时,自动把同一批 span 镜像到真实
    OTel Tracer(不强制安装,缺失则静默降级);
  * 事件驱动:harness 主循环在 run/step/model/tool/checkpoint 处抛出语义事件,
    Tracer 仅作为事件消费者重建 span 生命周期 —— 对 harness 零侵入。

埋点协议(harness 通过 on_event 抛出的事件):
  task_start   {task_id, follow_up_of, reason}
  step_start   {index}
  model_call   {index, model, prompt_tokens, completion_tokens, latency_ms}
  tool_call    {step_index, name, status, latency_ms}
  checkpoint   {step, reason}
  task_end     {status}
"""
from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import ensure_dir, now_iso, short_id


def _try_otel():
    """探测 opentelemetry-api,可用则返回其 trace 模块,否则 None。"""
    try:  # pragma: no cover - 依赖可选,在 CI 默认缺失
        from opentelemetry import trace as otel_trace
        return otel_trace
    except Exception:  # pragma: no cover
        return None


@dataclass
class Span:
    """一个追踪片段:对应一次 run / step / model 调用 / tool 调用 / checkpoint。"""

    name: str
    span_id: str = field(default_factory=lambda: short_id("span_"))
    parent_span_id: str | None = None
    trace_id: str | None = None
    start: str = field(default_factory=now_iso)
    end: str | None = None
    status: str = "ok"
    attributes: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    # 内部字段(不进导出)
    _start_ns: float = field(default=0.0, repr=False)
    _end_ns: float = field(default=0.0, repr=False)
    # OTel 镜像句柄(可选依赖,缺失时为 None)
    _otel_span: Any = field(default=None, repr=False)
    _otel_ctx: Any = field(default=None, repr=False)

    def close(self, status: str = "ok") -> None:
        self.end = now_iso()
        self.status = status

    @property
    def duration_ms(self) -> float:
        if self._end_ns != 0.0:
            return round((self._end_ns - self._start_ns) / 1_000_000.0, 3)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": list(self.events),
        }


class Tracer:
    """零依赖 Span 收集器 + OTLP 风格 JSON 导出 + 可选 OTel 桥接。

    用法(事件驱动):
        tracer = Tracer(artifacts_root=".mycoder/artifacts")
        harness.build(cfg, on_event=tracer.handle)
        # 任务结束后 tracer.export() 会把 trace.json 写到
        #   {artifacts_root}/{task_id}/trace.json
    """

    def __init__(self, artifacts_root: str | Path | None = None, enabled: bool = True,
                 service_name: str = "mycoder", trace_id: str | None = None):
        self.artifacts_root = str(artifacts_root) if artifacts_root else None
        self.enabled = enabled
        self.service_name = service_name
        self.trace_id = trace_id or short_id("trace_")
        self.spans: dict[str, Span] = {}
        self._run_span_id: str | None = None
        self._step_span_id: str | None = None
        self._task_id: str | None = None
        self._seq = 0
        # 可选 OTel 桥接
        self._otel = _try_otel()
        self._otel_tracer = None
        if self._otel is not None:  # pragma: no cover - 依赖可选
            try:
                self._otel_tracer = self._otel.get_tracer(service_name)
            except Exception:
                self._otel_tracer = None

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.spans.clear()
        self._run_span_id = None
        self._step_span_id = None
        self._task_id = None

    # ------------------------------------------------------------------
    # 事件入口:harness 把语义事件丢进来,这里重建 span 生命周期
    def handle(self, event: dict) -> None:
        if not self.enabled or not isinstance(event, dict):
            return
        etype = event.get("type")
        try:
            if etype == "task_start":
                self._on_task_start(event)
            elif etype == "step_start":
                self._on_step_start(event)
            elif etype == "model_call":
                self._on_leaf_span("model_call", event, parent_id=self._step_span_id)
            elif etype == "tool_call":
                self._on_leaf_span("tool:" + str(event.get("name", "?")),
                                   event, parent_id=self._step_span_id)
            elif etype == "checkpoint":
                self._on_leaf_span("checkpoint:" + str(event.get("reason", "")),
                                   event, parent_id=self._run_span_id)
            elif etype == "task_end":
                self._on_task_end(event)
        except Exception:  # 埋点绝不能拖垮主链路
            pass

    # ------------------------------------------------------------------
    def _on_task_start(self, event: dict) -> None:
        self.reset()
        self._task_id = event.get("task_id")
        span = self._start_span("run", attributes={
            "task_id": self._task_id,
            "follow_up_of": event.get("follow_up_of"),
            "reason": event.get("reason"),
            "service": self.service_name,
        })
        self._run_span_id = span.span_id

    def _on_step_start(self, event: dict) -> None:
        # 关闭上一个 step span(若还开着)
        if self._step_span_id and self._step_span_id in self.spans:
            self._end_span(self._step_span_id)
        span = self._start_span("step:" + str(event.get("index", "?")),
                                parent_id=self._run_span_id,
                                attributes={"step_index": event.get("index")})
        self._step_span_id = span.span_id

    def _on_leaf_span(self, name: str, event: dict, parent_id: str | None) -> None:
        latency = float(event.get("latency_ms", 0) or 0)
        now_ns = time.time_ns()
        span = self._start_span(name, parent_id=parent_id,
                                start_ns=now_ns - int(latency * 1_000_000),
                                end_ns=now_ns,
                                attributes={k: v for k, v in event.items()
                                            if k not in ("type",)})
        self._end_span(span.span_id, status=event.get("status", "ok"))

    def _on_task_end(self, event: dict) -> None:
        if self._step_span_id and self._step_span_id in self.spans:
            self._end_span(self._step_span_id)
        if self._run_span_id and self._run_span_id in self.spans:
            self._end_span(self._run_span_id, status=event.get("status", "ok"))
        self.export()

    # ------------------------------------------------------------------
    def _start_span(self, name: str, parent_id: str | None = None,
                    start_ns: float | None = None, end_ns: float | None = None,
                    attributes: dict | None = None) -> Span:
        now_ns = time.time_ns()
        span = Span(name=name, parent_span_id=parent_id, trace_id=self.trace_id,
                    attributes=dict(attributes or {}))
        span._start_ns = start_ns if start_ns else now_ns
        if end_ns:
            span._end_ns = end_ns
        self.spans[span.span_id] = span
        self._seq += 1
        # OTel 镜像(可选、隔离失败)
        if self._otel_tracer is not None:  # pragma: no cover - 依赖可选
            try:
                ctx = None
                if parent_id and parent_id in self.spans:
                    p = self.spans[parent_id]
                    if getattr(p, "_otel_ctx", None) is not None:
                        ctx = p._otel_ctx
                ot = self._otel_tracer.start_span(
                    name, start_time=span._start_ns, attributes=span.attributes,
                    parent=ctx)
                ot._mycoder_span_id = span.span_id
                span._otel_span = ot
                span._otel_ctx = self._otel.set_span_in_context(ot)
            except Exception:
                pass
        return span

    def _end_span(self, span_id: str, status: str = "ok") -> None:
        span = self.spans.get(span_id)
        if span is None or span.end is not None:
            return
        span.close(status)
        # OTel 镜像(可选、隔离失败)
        ot = span._otel_span
        if ot is not None:  # pragma: no cover - 依赖可选
            with contextlib.suppress(Exception):
                ot.end(end_time=span._end_ns or time.time_ns())

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "service": self.service_name,
            "task_id": self._task_id,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans.values()],
        }

    def export(self, path: str | Path | None = None) -> str | None:
        """写出 trace.json;不传 path 时落到 {artifacts_root}/{task_id}/trace.json。"""
        if not self.enabled:
            return None
        target = Path(path) if path else None
        if target is None and self.artifacts_root and self._task_id:
            target = Path(self.artifacts_root) / self._task_id / "trace.json"
        if target is None:
            return None
        ensure_dir(target.parent)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)
        target.write_text(payload, encoding="utf-8")
        return str(target)
