FROM python:3.13-slim AS builder

ENV POETRY_VERSION=2.0.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /app
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN useradd --create-home --shell /bin/sh appuser
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN chmod +x ./docker/entrypoint.sh && chown -R appuser:appuser /app
USER appuser

CMD ["./docker/entrypoint.sh"]
