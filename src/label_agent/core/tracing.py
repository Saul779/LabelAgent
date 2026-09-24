"""OpenTelemetry 初始化与 trace_id 透传（MQ 信封 v2 `trace_id` 字段，§3.1）。"""

from __future__ import annotations

from contextvars import ContextVar

_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def set_trace_id(trace_id: str | None) -> None:
    """将 trace_id 写入上下文变量，供日志与下游传播。"""
    _current_trace_id.set(trace_id)


def get_trace_id() -> str | None:
    """读取当前请求/任务的 trace_id。"""
    return _current_trace_id.get()


def setup_tracing(otlp_endpoint: str | None, service_name: str = "label-agent") -> None:
    """初始化 OTel TracerProvider；otlp_endpoint 为空时使用 NoOp Exporter。"""
    if not otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
