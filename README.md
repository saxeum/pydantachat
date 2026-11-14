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

## Tests

```bash
uv run pytest          # offline: TestModel/FunctionModel only
uv run pytest -m live  # opt-in smoke tests against the real DeepSeek API
```

The live suite is skipped unless `DEEPSEEK_API_KEY` is set (in the environment
or in `.env`). It asserts only invariants — completion, non-empty output, tool
execution — never exact wording; wording quality belongs to the eval harness.

## Evals

```bash
uv run python -m pydantachat.evals
```

Requires `DEEPSEEK_API_KEY`. Runs the evenness cases three times each — including
one that must use the `get_even` tool — and prints per-case results plus the
aggregate pass rate. This is a measurement, not a CI gate.

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
