.PHONY: install test lint format server ai up db-up migrate seed job scheduler perf

install:
	uv sync --all-packages

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

server:
	uv run --package bjk-server uvicorn bjk_server.main:app --reload --port 8000

ai:
	uv run --package bjk-ai uvicorn bjk_ai.main:app --reload --port 8001

up:
	docker compose up --build

db-up:
	docker compose up -d db

migrate:
	uv run --package bjk-server alembic -c apps/server/alembic.ini upgrade head

seed:
	uv run --package bjk-server python -m bjk_server.seed

# 예: make job name=nightly
job:
	uv run --package bjk-server python -m bjk_server.jobs $(name)

scheduler:
	uv run --package bjk-server python -m bjk_server.jobs.scheduler

# 부품 N종 성능 측정 (개발 DB 초기화). 예: make perf parts=1000
perf:
	uv run --package bjk-server python -m bjk_server.seed.perf --parts $(or $(parts),1000)
