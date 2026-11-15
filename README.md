# pydantachat

A minimal [Pydantic AI](https://ai.pydantic.dev) agent calling a configurable
model provider, with
OpenTelemetry traces sent to a local [Arize Phoenix](https://phoenix.arize.com).

## Run

```bash
uv sync
cp .env.example .env    # add the API keys you have
docker compose up -d    # optional: Phoenix UI on http://localhost:6006
uv run pydantachat
```

Python 3.14 or newer.

## Configuration

Everything except secrets lives in `config.json`:

```json
{
  "default_provider": "deepseek",
  "default_model": "deepseek-flash",
  "default_thinking": "high",
  "providers": {
    "deepseek": {
      "models": {
        "deepseek-flash": {
          "thinking": {
            "levels": ["low", "medium", "high", "max"],
            "can_disable": false
          }
        }
      }
    }
  },
  "tracing": {"endpoint": "http://localhost:6006", "service_name": "pydantachat"}
}
```

- `default_provider` / `default_model` / `default_thinking` — what runs when
  nothing else is asked for.
- `providers.<name>.models.<model>` — the models that may be requested from that
  provider, keyed by name, each declaring the thinking control that model
  actually offers. Thinking support belongs to the model, not the provider.
- `thinking.levels` — the effort levels that model accepts. Pydantic AI maps an
  unsupported level to the nearest accepted one, so declaring only the real
  range is what keeps a silent downgrade from being recorded as a measurement.
- `thinking.can_disable` — whether turning thinking off is honest for that
  model. Plenty of models always reason (`deepseek-flash`, `gpt-5-nano`); for
  those, `thinking=False` makes Pydantic AI send the lowest effort instead, so
  the app refuses the request rather than log an "off" run that wasn't.
- `default_thinking` is the default for the **default model**; any other model
  sends no thinking setting unless `--thinking` asks for one, rather than
  inheriting a level that model may not support.
- `tracing.endpoint` — OTLP base URL, e.g. `http://localhost:6006` for Phoenix;
  `null` turns tracing off. `tracing.service_name` defaults to `pydantachat`.

The file is validated as one unit at load, so a default that is missing from
its own allowed list fails immediately rather than on the first request, and an
unknown provider, model or level is reported along with the values that would
work.

Only secrets go in `.env`: one API key per provider, under the names Pydantic
AI itself reads — `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
i.e. `<PROVIDER>_API_KEY`. Only the selected provider's key is read, so all
three can sit there at once.

## Tests

```bash
uv run pytest          # offline: TestModel/FunctionModel only
uv run pytest -m live  # opt-in smoke tests against the real provider API
```

The live suite is skipped unless the default provider's API key is set (in the
environment or in `.env`). It asserts only invariants — completion, non-empty
output, tool execution — never exact wording; wording quality belongs to the
eval harness.

## Evals

```bash
uv run python -m pydantachat.evals
make evals-baseline   # save reports/baseline.json
make evals-compare    # run again and diff against the baseline
```

Requires the default provider's API key. Provider, model and thinking level
come from `config.json`; `--provider`, `--model` and `--thinking` override them
for a single run, and `--config` points at a different file:

```bash
uv run python -m pydantachat.evals --provider openrouter \
  --model nvidia/nemotron-3-super-120b-a12b --thinking low
```

Runs the evenness cases three times each — including one that must use the
`get_even` tool and one that must not use any tool — and prints per-case
results plus the aggregate pass rate. The
tool cases also check the tool spans and their arguments, so a correct answer
without the right tool call fails. Reports are written under `reports/` and are
git-ignored. Each run prints the model, effective thinking mode, total model
cost, and total thinking tokens. This is a measurement, not a CI gate.

## Tracing

Opt-in, driven by `tracing.endpoint` in `config.json`: set the OTLP base URL and
spans are exported over OTLP/HTTP to `<endpoint>/v1/traces`; leave it `null` and
the agent runs with no observers.
Pydantic AI emits plain OTel spans, so Jaeger, otel-tui or Langfuse are the same
change to a different URL.

`compose.yaml` turns Phoenix auth off because the port is bound to localhost
only — turn it back on if you expose it. Phoenix ingests traces only, so no
metrics provider is installed.

## License

MIT, © Saxeum.
