# pydantachat

A minimal [Pydantic AI](https://ai.pydantic.dev) agent calling DeepSeek, with
OpenTelemetry traces sent to a local [Arize Phoenix](https://phoenix.arize.com).

## Run

```bash
uv sync
cp .env.example .env    # fill in DEEPSEEK_API_KEY
docker compose up -d    # optional: Phoenix UI on http://localhost:6006
uv run pydantachat
```

Python 3.14 or newer.

## Tracing

Opt-in, and driven by one variable: set `OTEL_EXPORTER_OTLP_ENDPOINT` and spans
are exported over OTLP/HTTP; leave it empty and the agent runs with no observers.
Pydantic AI emits plain OTel spans, so Jaeger, otel-tui or Langfuse are the same
change to a different URL.

`compose.yaml` turns Phoenix auth off because the port is bound to localhost
only — turn it back on if you expose it. Phoenix ingests traces only, so no
metrics provider is installed.

## License

MIT, © Saxeum.
