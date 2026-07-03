.PHONY: up down logs db-up run migrate db-upgrade test test-all lint fmt typecheck precommit

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

db-up:
	docker compose up -d db

run:
	poetry run uvicorn finassist.app:create_app --factory --reload --host 0.0.0.0 --port 8000

migrate:
	poetry run alembic revision --autogenerate -m "$(m)"

db-upgrade:
	poetry run alembic upgrade head

test:
	poetry run pytest -m "not integration"

test-all:
	poetry run pytest

lint:
	poetry run ruff check .

fmt:
	poetry run ruff format .

typecheck:
	poetry run mypy src tests

precommit:
	poetry run pre-commit run --all-files
