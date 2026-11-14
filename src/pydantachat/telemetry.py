"""Opt-in OpenTelemetry setup for pydantic-ai.

Pydantic AI emits plain OTel spans, so traces can go to any OTLP backend
(Phoenix in `compose.yaml`, Jaeger, Langfuse, otel-tui, ...) by setting
`OTEL_EXPORTER_OTLP_ENDPOINT`. With it unset, tracing stays off and the
agent runs with no observers.

Deliberately vendor-neutral: only the OTel SDK and the OTLP/HTTP exporter.
No metrics provider is installed, so token-count meters are no-ops -- Phoenix
only ingests traces and answers `/v1/metrics` with 405.
"""

import atexit
import os


def setup_telemetry() -> None:
    """Export pydantic-ai spans over OTLP when an endpoint is configured."""
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import set_tracer_provider
    from pydantic_ai import Agent

    tracer_provider = TracerProvider(
        resource=Resource.create(
            {"service.name": os.getenv("OTEL_SERVICE_NAME", "pydantachat")}
        ),
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(tracer_provider)
    # BatchSpanProcessor does not register its own atexit hook, so a short CLI
    # run would exit before the final batch is flushed and lose its traces.
    atexit.register(tracer_provider.shutdown)

    Agent.instrument_all()
