"""OpenTelemetry tracing setup and helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_tracing_configured = False


def configure_tracing(service_name: str | None = None) -> None:
    """Configure OTLP export and library instrumentors. Safe to call multiple times."""
    global _tracing_configured
    if not settings.tracing_enabled:
        return
    if _tracing_configured:
        return

    name = service_name or settings.otel_service_name
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=True,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.db.session import engine

        SQLAlchemyInstrumentor().instrument(engine=engine)
        RedisInstrumentor().instrument()

        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor

            RequestsInstrumentor().instrument()
        except Exception as req_exc:
            log.warning("requests_tracing_skipped", error=str(req_exc))

        _tracing_configured = True
        log.info(
            "tracing_configured",
            service_name=name,
            endpoint=settings.otel_exporter_otlp_endpoint,
        )
    except Exception as exc:
        log.warning("tracing_setup_failed", error=str(exc))


def instrument_fastapi(app) -> None:
    if not settings.tracing_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health,metrics",
        )
    except Exception as exc:
        log.warning("fastapi_tracing_failed", error=str(exc))


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def record_span_exception(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)[:500]))


@contextmanager
def start_span(
    tracer_name: str,
    span_name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    tracer = get_tracer(tracer_name)
    with tracer.start_as_current_span(span_name, attributes=attributes or {}) as span:
        try:
            yield span
        except Exception as exc:
            record_span_exception(span, exc)
            raise


@contextmanager
def storage_span(
    operation: str,
    bucket: str,
    object_key: str | None = None,
) -> Iterator[Span]:
    attrs: dict[str, Any] = {
        "storage.operation": operation,
        "object.bucket": bucket,
    }
    if object_key:
        attrs["object.key"] = object_key
    with start_span("app.object_storage", f"object_storage.{operation}", attributes=attrs) as span:
        yield span
