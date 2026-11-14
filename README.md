# pydantachat

A minimal [Pydantic AI](https://ai.pydantic.dev) agent calling a configurable
model provider, with
OpenTelemetry traces sent to a local [Arize Phoenix](https://phoenix.arize.com).

## Run

```bash
uv sync
cp .env.example .env    # fill in PROVIDER_API_KEY
docker compose up -d    # optional: Phoenix UI on http://localhost:6006
uv run pydantachat
```

Python 3.14 or newer.

## Configuration

Set these in `.env` or the environment:

- `PROVIDER_API_KEY` — required. It is mapped to the provider's expected API
  key environment variable when the agent is built.
- `PROVIDER` — Pydantic AI provider name, e.g. `deepseek`.
- `MODEL` — model name within that provider, e.g. `deepseek-flash`.
- `THINKING_LEVEL` — `true`, `false`, or `minimal`/`low`/`medium`/`high`/
  `xhigh`/`max`; empty uses the provider default.

## Tests

```bash
uv run pytest          # offline: TestModel/FunctionModel only
uv run pytest -m live  # opt-in smoke tests against the real provider API
```

The live suite is skipped unless `PROVIDER_API_KEY` is set (in the environment
or in `.env`). It asserts only invariants — completion, non-empty output, tool
execution — never exact wording; wording quality belongs to the eval harness.

## Evals

```bash
uv run python -m pydantachat.evals
make evals-baseline   # save reports/baseline.json
make evals-compare    # run again and diff against the baseline
```

Requires `PROVIDER_API_KEY`. Runs the evenness cases three times each — including
one that must use the `get_even` tool and one that must not use any tool — and
prints per-case results plus the aggregate pass rate. The tool cases also check
the tool spans and their arguments, so a correct answer without the right tool
call fails. Reports are written under `reports/` and are git-ignored. Each run
prints the model, effective thinking mode, total model cost, and total thinking
tokens. This is a measurement, not a CI gate.

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
