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

# Три прогона pytest идут ПАРАЛЛЕЛЬНО на одном PostgreSQL (W14-S2). Базы у них свои и не пересекаются:
# ядро и SQLAlchemy — rt_bus_sa; Django psycopg2 — rt_bus_dj_psycopg2 и rt_bus_schema_sa_psycopg2; Django psycopg 3 — rt_bus_dj_psycopg
# и rt_bus_schema_sa_psycopg (tests/conftest.py, tests/dj/conftest.py, test_django_schema.py). Вывод каждого — в свой файл и после
# завершения всех трёх подряд на экран, чтобы строки не перемешивались; код выхода — провал любого из трёх.
.PHONY: _test
_test:
	uv sync --frozen
	@d=$$(mktemp -d); trap 'rm -rf "$$d"' EXIT; \
	uv run --no-sync pytest >"$$d/1-core.log" 2>&1 & p1=$$!; \
	RT_BUS_DJANGO_DRIVER=psycopg2 uv run --no-sync pytest tests/dj >"$$d/2-django-psycopg2.log" 2>&1 & p2=$$!; \
	RT_BUS_DJANGO_DRIVER=psycopg uv run --no-sync pytest tests/dj >"$$d/3-django-psycopg.log" 2>&1 & p3=$$!; \
	rc=0; wait $$p1 || rc=1; wait $$p2 || rc=1; wait $$p3 || rc=1; \
	for f in "$$d"/*.log; do echo "=== $$(basename "$$f" .log) ==="; cat "$$f"; done; \
	[ $$rc -eq 0 ] || echo "rt-bus: pytest упал хотя бы в одном из трёх прогонов (см. выше)"; \
	exit $$rc

.PHONY: migrations-check
migrations-check: ## Миграция Django соответствует моделям (без базы)
	DJANGO_SETTINGS_MODULE=tests.django_settings uv run python -W ignore::RuntimeWarning -m django makemigrations rt_bus --check --dry-run

.PHONY: check
check: lint typecheck migrations-check test ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: clean
clean: ## Удалить .venv и кэши
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
