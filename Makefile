.PHONY: install test lint format server ai up

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
