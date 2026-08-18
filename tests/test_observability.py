"""可观测性:链路追踪(Tracer/Span)与结构化 JSON 日志。"""
import json
from pathlib import Path

import pytest

from mycoder.observability import Span, Tracer
from mycoder.state import TaskInput


def _feed(tracer: Tracer) -> None:
    """喂入一组与 harness 等价的语义事件。"""
    tracer.handle({"type": "task_start", "task_id": "t-obs", "ts": "t"})
    tracer.handle({"type": "step_start", "index": 0, "ts": "t"})
    tracer.handle({"type": "model_call", "index": 0, "model": "mock",
                   "prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 20, "ts": "t"})
    tracer.handle({"type": "tool_call", "step_index": 0, "name": "file_read",
                   "status": "ok", "latency_ms": 3, "ts": "t"})
    tracer.handle({"type": "step_end", "index": 0, "ts": "t"})
    tracer.handle({"type": "checkpoint", "step": 1, "reason": "interval", "ts": "t"})
    tracer.handle({"type": "task_end", "status": "completed", "ts": "t"})


class TestTracer:
    def test_basic_spans(self, tmp_path):
        tr = Tracer(artifacts_root=tmp_path, enabled=True)
        _feed(tr)
        d = tr.to_dict()
        assert d["task_id"] == "t-obs"
        names = {s["name"] for s in d["spans"]}
        assert "run" in names
        assert any(n.startswith("step:") for n in names)
        assert any(n == "model_call" for n in names)
        assert any(n == "tool:file_read" for n in names)
        run = [s for s in d["spans"] if s["name"] == "run"][0]
        assert run["status"] == "completed"
        assert run["end"] is not None

    def test_export_writes_trace_json(self, tmp_path):
        tr = Tracer(artifacts_root=tmp_path, enabled=True)
        _feed(tr)
        out = tr.export()
        assert out is not None
        p = Path(out)
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["trace_id"]
        assert len(data["spans"]) >= 4

    def test_disabled_no_export(self, tmp_path):
        tr = Tracer(artifacts_root=tmp_path, enabled=False)
        _feed(tr)
        assert tr.export() is None

    def test_otel_bridge_does_not_crash(self, tmp_path):
        # 无论是否安装 opentelemetry-api,埋点都不应抛错
        tr = Tracer(artifacts_root=tmp_path, enabled=True)
        _feed(tr)
        assert tr.to_dict()["span_count"] >= 1

    def test_span_duration_ms(self):
        s = Span(name="x")
        s._start_ns = 0
        s._end_ns = 5_000_000  # 5_000_000 ns = 5 ms
        assert s.duration_ms == 5.0


class TestHarnessTracing:
    def test_run_produces_trace_json(self, tmp_path, make_harness):
        h = make_harness(script=[{"content": "done"}])
        res = h.run(TaskInput(task_id="obs1", goal="g"))
        assert res.status == "completed"
        trace = tmp_path / "artifacts" / "obs1" / "trace.json"
        assert trace.exists()
        data = json.loads(trace.read_text(encoding="utf-8"))
        names = {s["name"] for s in data["spans"]}
        assert "run" in names
        assert any(n == "model_call" for n in names)


class TestJsonLogging:
    def test_json_formatter_parseable(self):
        from mycoder.agent.harness import JsonFormatter
        import logging

        fmt = JsonFormatter()
        rec = logging.LogRecord("x", logging.INFO, "p", 1, "hello %s", ("world",), None)
        obj = json.loads(fmt.format(rec))
        assert obj["level"] == "INFO"
        assert "hello world" in obj["message"]
        assert obj["logger"] == "x"
