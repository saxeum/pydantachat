# pydantachat

A minimal [Pydantic AI](https://ai.pydantic.dev) agent calling a configurable
model provider, with
OpenTelemetry traces sent to a local [Arize Phoenix](https://phoenix.arize.com).

## Run

```bash
uv sync
cp .env.example .env    # add the API key for your provider
docker compose up -d    # optional: Phoenix UI on http://localhost:6006
uv run pydantachat
```

Python 3.14 or newer.

## Configuration

Set these in `.env` or the environment:

- `PROVIDER` — Pydantic AI provider name, e.g. `deepseek`, `openai`,
  `openrouter`.
- `MODEL` — model name within that provider, e.g. `deepseek-flash`.
- `<PROVIDER>_API_KEY` — the key for the selected provider, with `-` replaced
  by `_` and uppercased: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`,
  `OPENROUTER_API_KEY`. Only the selected provider's key is read, so several
  keys can live in `.env` at once.
- `THINKING_LEVEL` — `true`, `false`, or `minimal`/`low`/`medium`/`high`/
  `xhigh`/`max`; empty uses the provider default.

`.env` is loaded once at import into `pydantachat.settings.settings`, which
exposes a `ModelConfig` (`model_id`, `model_settings`, `api_key_env`,
`has_api_key`). Switching provider/model/thinking is just a change to those
variables — nothing in the code names a provider. Callers that want an
explicit configuration can pass `build_agent(config=ModelConfig(...))`.

## Tests

```bash
uv run pytest          # offline: TestModel/FunctionModel only
uv run pytest -m live  # opt-in smoke tests against the real provider API
```

The live suite is skipped unless the active provider's API key is set (in the
environment or in `.env`). It asserts only invariants — completion, non-empty
output, tool execution — never exact wording; wording quality belongs to the
eval harness.

## Evals

```bash
uv run python -m pydantachat.evals
make evals-baseline   # save reports/baseline.json
make evals-compare    # run again and diff against the baseline
```

Requires the active provider's API key. Runs the evenness cases three times
each — including one that must use the `get_even` tool and one that must not
use any tool — and prints per-case results plus the aggregate pass rate. The
tool cases also check the tool spans and their arguments, so a correct answer
without the right tool call fails. Reports are written under `reports/` and are
git-ignored. Each run prints the model, effective thinking mode, total model
cost, and total thinking tokens. This is a measurement, not a CI gate.

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
