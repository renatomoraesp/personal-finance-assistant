# AGENTS.md

AI-native personal finance assistant: a Telegram bot (aiogram) that answers questions about the
user's real financial life in Brazilian Portuguese, using Open Finance data from Pluggy and an LLM
(Gemma 4 26B via OpenRouter) with native tool calling. Async FastAPI monolith, PostgreSQL,
single-user for now.

## Setup & commands

Requires Python 3.13, Poetry 2.x, and Docker (Postgres + testcontainers).

```bash
poetry install                 # deps (dev included)
make db-up                     # start only Postgres via docker compose
make run                       # run the app on the host against dockerized Postgres
make up / make down            # full stack in Docker
make test                      # unit tests only (fast, no Docker)
make test-all                  # full suite incl. integration (needs Docker daemon)
make lint / make fmt           # ruff check / ruff format
make typecheck                 # mypy (strict)
make migrate m="message"       # alembic autogenerate (needs db up)
make db-upgrade                # alembic upgrade head
poetry run pre-commit run --all-files
```

Configuration comes from `.env` (see `.env.example`). Never commit `.env` or print secrets.

## Architecture map

- `src/finassist/core/` — settings (pydantic-settings), structlog config.
- `src/finassist/db/` — SQLAlchemy 2.0 async models, session factory. Migrations in `migrations/`.
- `src/finassist/repositories/` — DB access only; no business logic.
- `src/finassist/services/` — business logic: `sync` (Pluggy → DB), `finance` (queries/aggregations),
  `agent/` (LLM tool-calling loop, tool schemas, pt-BR system prompt).
- `src/finassist/integrations/` — outbound HTTP clients (Pluggy, OpenRouter). Thin, injectable.
- `src/finassist/telegram/` — aiogram bot. Handlers must stay thin: parse → service → reply.
- `src/finassist/api/` — FastAPI routes (`/healthz`, `/readyz`); the bot runs from app lifespan.

## Code style

- Python 3.13, fully typed; mypy runs `strict`. Don't add `type: ignore` without a reason comment.
- Ruff is the only linter/formatter (line length 100). Run `make fmt` before finishing.
- SQLAlchemy 2.0 style only (`Mapped[...]`, `mapped_column`); async everywhere — no blocking I/O
  in async paths (ruff's ASYNC rules enforce this).
- Money is `Decimal`/`Numeric(14,2)`, never float. Timestamps are timezone-aware UTC; user-facing
  date math uses `settings.timezone` (America/Sao_Paulo).
- Logging via structlog only; no `print`, no stdlib `logging.basicConfig`.
- User-facing bot copy is Brazilian Portuguese; code, comments, and logs are English.

## Domain gotchas

- Pluggy transaction `amount` sign conventions differ by account type. We store `amount` verbatim
  and treat `type` (DEBIT/CREDIT) as the direction authority. All "money out" logic lives in ONE
  place: `services/finance.py`. Never re-derive outflow logic elsewhere.
- Pluggy API keys expire after 2h; the client re-auths lazily. Don't cache clients across settings.
- A sync is a HARD refresh: `PATCH /items/{id}` asks Pluggy to re-sync with the bank, we wait
  (bounded) for the item to leave UPDATING, then pull. Pluggy forbids batch/cron update polling —
  refreshes must stay user-triggered and throttled by the `SYNC_MAX_AGE_MINUTES` staleness gate;
  treat 409 on PATCH as benign (already syncing / too frequent).
- Agent read tools are fire-and-forget: `BackgroundSyncScheduler.kick_if_stale()` answers from
  cache and spawns at most one in-process refresh task; only `/sync` and the `sync_now` tool
  block until the refresh finishes. Don't make read paths await a bank sync.
- Transactions come from `GET /v2/transactions` (cursor pagination via `after`/`next`). The v1
  page-based endpoint is deprecated and is removed after 2026-12-31 — don't reintroduce it.
- `PATCH /items` (bank refresh) is rate-limited to 20/min and user-triggered only — never poll it.

## Testing

- Integration tests are the backbone (`tests/integration/`, marked `integration`): real Postgres via
  testcontainers, Alembic migrations applied for real, outbound HTTP mocked with respx at the httpx
  layer. Unit tests cover pure logic and client behavior.
- New behavior needs tests at the same level as the behavior: service logic → integration test
  against the real DB; HTTP client details → unit test with respx.
- `pytest -m "not integration"` must stay green without Docker.

## Committing

- `pre-commit run --all-files` must pass before any commit — this is an invariant, not a suggestion.
- Never commit `.env`, credentials, or generated artifacts. Don't commit unless asked.
