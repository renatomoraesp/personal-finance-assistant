# CLAUDE.md

@AGENTS.md

Everything in `AGENTS.md` applies. Claude-specific working notes below.

## Workflow

- Verify before claiming done: run `make lint`, `make typecheck`, `make test` (and `make test-all`
  when touching DB/services — start the Docker daemon if needed). "Should work" is not done.
- Pre-commit is a commit invariant: `poetry run pre-commit run --all-files` must be clean before
  committing anything. Never use `--no-verify`.
- Plan multi-file changes before editing; prefer small, reviewable diffs. Don't refactor unrelated
  code in the same pass.
- Read neighboring code first and match it — this repo is deliberately consistent (SQLAlchemy 2.0
  style, structlog, thin handlers, service-layer logic). Grep for an existing pattern before
  inventing one.

## Things Claude gets wrong here without being told

- The agent's tool loop serializes tool results with `json.dumps(..., default=str)` because results
  carry `Decimal` and `date`. Keep it that way; don't "fix" it to floats.
- aiogram handlers receive services via dispatcher workflow data / middleware injection — don't
  instantiate services or sessions inside handlers.
- Integration tests apply real Alembic migrations against a testcontainer; if you change models,
  generate a migration (`make migrate m="..."`) or those tests fail — that's the point.
- The bot replies in pt-BR; don't translate bot copy to English when editing handlers or prompts.
- OpenRouter is OpenAI-SDK-compatible; the model id lives in settings (`OPENROUTER_MODEL`), never
  hardcode it.

## Secrets

`.env` holds real credentials (Telegram token, Pluggy client secret, OpenRouter key). Never read it
into output, never log `SecretStr` values, never commit it.
