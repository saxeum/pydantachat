# pydantachat

A minimal [Pydantic AI](https://ai.pydantic.dev) agent calling a configurable
model provider, with
OpenTelemetry traces sent to a local [Arize Phoenix](https://phoenix.arize.com).

The agent answers questions about the signed-in customer's orders. The orders
live in SQLite behind an HTTP API that trusts only a short-lived, customer-scoped
token, so the model never decides whose data it can read. See
[Orders and auth](#orders-and-auth).

## Run

```bash
uv sync
cp .env.example .env    # add the API keys you have
docker compose up -d    # optional: Phoenix UI on http://localhost:6006
uv run pydantachat      # single-tenant CLI, acts for a local demo customer
```

Python 3.14 or newer.

## Output

`Chat.send` returns text; `Chat.send_stream` yields text deltas as the model
produces them. The model is told to call `get_orders` before answering anything
about orders, and not to guess:

```
> what is the status of my latest order?
Your most recent order (2026-11-01) was delivered; it totalled 89.99 USD.
```

The tool returns only this customer's rows, with the customer id removed and
totals already formatted. What makes that true is not the prompt: the tool takes
no customer argument and the identity comes from the wrapper's token.

## Web API

```bash
make dev   # uvicorn pydantachat.app:api --reload on :8000
```

Open <http://localhost:8000>: sign in with an allowlisted Google account and
chat. The page is public and asks `/api/me` who is signed in; everything under
`/api` requires credentials.

The styling uses the design tokens from numbat's web app
(`apps/web/src/styles/globals.css`): grey canvas, hairline borders, one indigo
accent, Geist for UI. `theme.css` holds the tokens verbatim (same variable names)
and `app.css` the components. The Geist and JetBrains Mono woff2 files are
vendored under `static/fonts/`, never loaded from a CDN, because the page's CSP
is `default-src 'self'`. Dark mode follows `prefers-color-scheme`.

The same agent over HTTP, with two entry points over `Chat.send` and
`Chat.send_stream`:

| Endpoint | What it does |
| --- | --- |
| `POST /api/chat` | one complete text answer |
| `POST /api/chat/stream` | the same answer as server-sent events, one `{"text": ...}` delta per `data:` frame, ending with `data: [DONE]` |
| `GET /api/orders` | the token customer's orders (orders token only) |
| `GET /api/customers/{id}/orders` | the same data, 403 unless `id` is the token's customer |
| `GET /api/me` | `{email, name, mode}` — `mode` is `cookie` or `bearer` |
| `GET /health` | liveness; touches no configuration |
| `GET /ready` | 503 until the config and the provider key are present |

Requests carry `{message, session_id}`; `message` is capped at 4000 characters
and a missing `session_id` starts a new conversation. Sessions are in-process,
so the app runs a single worker and says so if `UVICORN_WORKERS`/`WEB_CONCURRENCY`
asks for more (see #34 for the shared-store follow-up).

### Auth

Google OIDC, two credential types resolving to one identity:

- **Cookie session** for the browser: `GET /login` → Google → `GET /auth` sets an
  HttpOnly cookie and redirects to `/`; `GET /logout` clears it. Writes must be
  `application/json` from our own origin (the CSRF gate).
- **Bearer** for scripts: send a Google ID token obtained with our client id as
  its audience. The server never issues tokens, it only verifies them against
  Google's keys. `GET /login?format=json` returns the ID token as JSON at the end
  of the same flow, for hand-testing.

`ALLOWED_EMAILS` is required and **fails closed** — an empty list refuses to
start rather than admitting any Google account. `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `ALLOWED_EMAILS` and `APP_BASE_URL`
come from `.env`; register `<APP_BASE_URL>/auth` as a redirect URI on the shared
Google client.

Agent failures become generic responses — `502` for provider problems, `500` for
a configuration error, `401`/`403` for credentials — with the detail logged
rather than returned.

### Orders and auth

The API stops trusting the agent and trusts only a credential:

- The user signs in with Google OIDC, so the wrapper knows the email. It maps the
  email to a `customers` row and mints a signed token whose claim is that
  customer id and the chat session id, valid for two minutes.
- The tool is bound to that token's customer. It takes **no customer argument**,
  calls `GET /api/orders` over HTTP, and returns rows. The token is minted per
  call and never enters the prompt, the tool result, or the transcript.
- `GET /api/orders` derives the customer from the token and nothing else. The
  route does not accept the browser cookie or a Google ID token, so only the
  agent's scoped credential can read orders.

That is our own signed token, not an identity-provider on-behalf-of grant; the
secret is `SESSION_SECRET` under a distinct salt. The test that matters is the
failure one: a token for customer A asking for B's orders gets 403, and that test
fails if the claim check is removed.

Read-only, single-customer scope bounds the damage. It does not make the tool
safe for writes: `cancel_order` or `issue_refund` would need server-side business
rules and confirmation of their own.

For a browser-level check of the page (needs the app running and
`uv run --with playwright`): `python scripts/ui_smoke.py`. It forges a session
cookie from `SESSION_SECRET`, so it skips the Google round-trip, and it is not
part of CI.

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
  "tracing": {"endpoint": "http://localhost:6006", "service_name": "pydantachat"},
  "db_path": "data.db"
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
- `thinking.can_disable` — whether "off" is a real state for that model.
  `deepseek-flash` thinks *by default* but can be turned off, which is the
  distinction this field records; `gpt-5-nano` accepts only
  `minimal`/`low`/`medium`/`high` and has no `none`, so `thinking=False` makes
  Pydantic AI send `minimal` instead. Claiming "off" there would log a run that
  was still thinking, so the request is refused. Pydantic AI translates
  `thinking=False` into whatever the provider uses to stop reasoning:
  `reasoning_effort='none'`, an Anthropic-style `reasoning: {"effort": "none"}`,
  or `{"thinking": {"type": "disabled"}}`.
- `default_thinking` is the default for the **default model**; any other model
  sends no thinking setting unless `--thinking` asks for one, rather than
  inheriting a level that model may not support.
- `tracing.endpoint` — OTLP base URL, e.g. `http://localhost:6006` for Phoenix;
  `null` turns tracing off. `tracing.service_name` defaults to `pydantachat`.
- `db_path` — the SQLite file. It is created and seeded at startup: every entry
  in `ALLOWED_EMAILS` gets a customer row and three demo orders, idempotently,
  so an email with no row is a 403 rather than an empty list.

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
make test        # or: uv run pytest          -- offline, TestModel/FunctionModel only
make test-live   # or: uv run pytest -m live  -- hits the real provider API
make lint        # ruff check + ruff format --check
make typecheck   # basedpyright, standard mode
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

Runs the order cases three times each: one must cite every order, one must
answer a status question, and one asks about another customer and must return no
order data. The first two also assert that `get_orders` ran, so a correct answer
with no tool call fails. Reports are written under `reports/` and are git-ignored.
Each run seeds a throwaway database, so it never touches `data.db`, and prints
the model, effective thinking mode, total model cost, and total thinking tokens.
This is a measurement, not a CI gate.

`.github/workflows/live.yml` does the same once a week (and on manual dispatch):
it runs the live smoke tests, then `evals-compare` against the previous run's
report and uploads `reports/` as an artifact. It needs a `DEEPSEEK_API_KEY`
repository secret. A failing assertion only shows up in the report; a missing
key or a network error fails the run.

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
