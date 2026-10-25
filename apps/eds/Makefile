# RailTech EDS — команды разработки (docs/systems/eds/CONVENTIONS.md §3). Docker нужен только для `make test`:
# тесты идут против настоящего PostgreSQL (EDS_TEST_DATABASE_URL или одноразовый postgres:17 — scripts/with_pg.sh).

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Зависимости (uv sync --frozen)
	uv sync --frozen

.PHONY: lint
lint: ## ruff check + ruff format --check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: typecheck
typecheck: ## mypy --strict
	uv run mypy app tests alembic

.PHONY: test-unit
test-unit: ## Только тесты без базы (секунды, Docker не нужен)
	uv run pytest -m "not pg"

.PHONY: test
test: ## Все тесты, в т. ч. на PostgreSQL (без EDS_TEST_DATABASE_URL — одноразовый postgres:17 в Docker)
	./scripts/with_pg.sh uv run pytest

.PHONY: check
check: lint typecheck test ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: migration
migration: ## Создать миграцию: make migration m="add letters" (нужна база по EDS_DATABASE_URL)
	@test -n "$(m)" || (echo 'Укажите описание: make migration m="..."'; exit 1)
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: clean
clean: ## Удалить .venv и кэши
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
