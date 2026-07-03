# Personal Finance Assistant

A personal, AI-native finance assistant for Brazil, delivered as a Telegram bot. You talk to it
like you'd talk to ChatGPT or Claude — in Brazilian Portuguese, about your actual money:

> **você:** quanto gastei hoje?
> **bot:** Hoje você gastou R$ 187,40 — R$ 62,90 em alimentação, R$ 74,50 em transporte e
> R$ 50,00 num Pix. Quer ver os lançamentos?

Under the hood it pulls your real account and transaction data through
[Pluggy](https://pluggy.ai) (Open Finance Brasil) and reasons over it with an LLM
(Gemma 4 26B via [OpenRouter](https://openrouter.ai)) using native tool calling — the model
queries your synced data on demand instead of hallucinating numbers.

Single-user by design for now; the architecture is a modular async monolith intended to split
into services later if it ever becomes a product.

## How it works

```
Telegram ──▶ aiogram handlers (thin)
                  │
                  ▼
             AgentService ──── tool-calling loop ────▶ OpenRouter (Gemma 4 26B)
                  │ tools: get_balances, list_transactions,
                  │        summarize_spending, sync_now
                  ▼
             FinanceService / SyncService
                  │                    │
                  ▼                    ▼
              PostgreSQL ◀──────── Pluggy API (Open Finance)
```

- **Sync**: transactions and balances are cached in Postgres; a staleness gate refreshes from
  Pluggy before the agent answers data questions. `/sync` forces it.
- **Agent**: the LLM never sees raw credentials and never invents data — factual answers come
  from tool calls against the local database.
- **FastAPI** hosts health endpoints (`/healthz`, `/readyz`) and the app lifecycle; the bot runs
  as a polling task inside the app lifespan (webhook mode is a planned follow-up).

## Stack

Python 3.13 · FastAPI · aiogram 3 · SQLAlchemy 2.0 (async) + Alembic · PostgreSQL 17 ·
Pydantic 2 · httpx · structlog · Poetry 2 · Docker Compose · pytest + testcontainers · ruff · mypy (strict)

## Getting started

Prerequisites: Docker (with the daemon running), Python 3.13, Poetry 2.x.

```bash
cp .env.example .env    # fill in: Telegram bot token, Pluggy credentials, OpenRouter key
make up                 # builds the image, starts Postgres + app, runs migrations
```

That's it — message your bot on Telegram. `/start` registers you; only Telegram user ids listed
in `TELEGRAM_ALLOWED_USER_IDS` are accepted.

### Local development (app on host, DB in Docker)

```bash
poetry install
make db-up              # Postgres only
make db-upgrade         # apply migrations
make run                # uvicorn with the bot polling
```

### Configuration

Everything is a `.env` variable (see `.env.example` for the full annotated list). The essentials:

| Variable | What it is |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated Telegram user ids allowed to use the bot |
| `PLUGGY_CLIENT_ID` / `PLUGGY_CLIENT_SECRET` | From the [Pluggy dashboard](https://dashboard.pluggy.ai) |
| `PLUGGY_ITEM_IDS` | Comma-separated ids of your connected bank(s) |
| `OPENROUTER_API_KEY` | From [openrouter.ai](https://openrouter.ai/keys) |
| `OPENROUTER_MODEL` | Defaults to `google/gemma-4-26b-a4b-it` |

## Development

```bash
make test               # unit tests (fast, no Docker)
make test-all           # full suite — spins up real Postgres via testcontainers
make lint / make fmt    # ruff
make typecheck          # mypy --strict
make migrate m="add x"  # alembic autogenerate
poetry run pre-commit install   # once; hooks then run on every commit
```

Testing philosophy: **integration-first**. The tests that matter run against a real Postgres
(testcontainers) with real Alembic migrations applied, mocking only the outbound HTTP edges
(Pluggy, OpenRouter) with respx. Unit tests cover pure logic — sign conventions, the agent's
tool loop, client auth/pagination. `pre-commit run --all-files` (ruff → mypy → lock check) is
the commit gate.

See [`AGENTS.md`](AGENTS.md) for the agent/contributor guide and domain gotchas.

## Roadmap

- Proactive nudges (daily spend limits, "you're over budget" pushes) via webhooks + scheduler
- WhatsApp as an alternative front-end
- Telegram webhook mode behind the existing FastAPI app
- Multi-user support (per-user Pluggy items, consent flow via Pluggy Connect)

## Disclaimer

Personal project, not financial advice, no warranty. Your financial data stays in your own
Postgres instance; the only third parties involved are the ones you configure (Pluggy,
OpenRouter, Telegram).
