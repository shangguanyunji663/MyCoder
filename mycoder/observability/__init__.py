"""可观测性包:轻量链路追踪(零依赖,OTLP 风格导出,可选 OTel 桥接)。"""
from .tracing import Span, Tracer, _try_otel

__all__ = ["Span", "Tracer", "_try_otel"]
