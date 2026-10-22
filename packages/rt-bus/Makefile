# rt-bus — библиотека шины событий (docs/architecture/rt-bus.md). Инструменты — как apps/platform/bff: uv, ruff, mypy, pytest.
# Тесты адаптеров идут против настоящего PostgreSQL: RT_BUS_TEST_DATABASE_URL или одноразовый postgres:17 в Docker.

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Зависимости (uv sync --frozen)
	uv sync --frozen

.PHONY: lint
lint: ## ruff check + ruff format --check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: typecheck
typecheck: ## mypy --strict (django-stubs)
	uv run mypy rt_bus tests

.PHONY: test-unit
test-unit: ## Только тесты без базы (секунды, Docker не нужен)
	uv run pytest -m "not pg"

.PHONY: test
test: ## Все тесты: ядро, SQLAlchemy (psycopg, asyncpg), Django (psycopg2 как ERP, psycopg) — на PostgreSQL
	RT_BUS_REQUIRE_PG=1 ./scripts/with_pg.sh $(MAKE) --no-print-directory _test

.PHONY: _test
_test:
	uv run pytest
	RT_BUS_DJANGO_DRIVER=psycopg2 uv run pytest tests/dj
	RT_BUS_DJANGO_DRIVER=psycopg uv run pytest tests/dj

.PHONY: migrations-check
migrations-check: ## Миграция Django соответствует моделям (без базы)
	DJANGO_SETTINGS_MODULE=tests.django_settings uv run python -W ignore::RuntimeWarning -m django makemigrations rt_bus --check --dry-run

.PHONY: check
check: lint typecheck migrations-check test ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: clean
clean: ## Удалить .venv и кэши
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
