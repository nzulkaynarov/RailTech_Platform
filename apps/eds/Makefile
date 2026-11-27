# RailTech EDS — команды разработки (docs/systems/eds/CONVENTIONS.md §3). Docker нужен только для `make test`:
# тесты идут против настоящего PostgreSQL (EDS_TEST_DATABASE_URL или одноразовый postgres:17 — scripts/with_pg.sh).

SHELL := /bin/bash
# Общий предел тяжёлых проверок (два слота на машину): lint/typecheck/test/check берут слот целиком, вложенные — нет (scripts/heavy-lock.sh).
HEAVY := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../../scripts/heavy-lock.sh)
.DEFAULT_GOAL := help

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Зависимости (uv sync --frozen)
	uv sync --frozen

.PHONY: lint
lint: ## ruff check + ruff format --check
	@$(HEAVY) $(MAKE) --no-print-directory lint-run

.PHONY: lint-run
lint-run:
	uv run ruff check .
	uv run ruff format --check .

.PHONY: typecheck
typecheck: ## mypy --strict
	@$(HEAVY) $(MAKE) --no-print-directory typecheck-run

.PHONY: typecheck-run
typecheck-run:
	uv run mypy app tests alembic

.PHONY: test-unit
test-unit: ## Только тесты без базы (секунды, Docker не нужен)
	@$(HEAVY) $(MAKE) --no-print-directory test-unit-run

.PHONY: test-unit-run
test-unit-run:
	uv run pytest -m "not pg"

.PHONY: test
test: ## Все тесты, в т. ч. на PostgreSQL (без EDS_TEST_DATABASE_URL — одноразовый postgres:17 в Docker)
	@$(HEAVY) $(MAKE) --no-print-directory test-run

.PHONY: test-run
test-run:
	./scripts/with_pg.sh uv run pytest

.PHONY: check
check: ## Всё вышеперечисленное — обязательно перед коммитом
	@$(HEAVY) $(MAKE) --no-print-directory check-run

.PHONY: check-run
check-run: lint typecheck test

.PHONY: migration
migration: ## Создать миграцию: make migration m="add letters" (нужна база по EDS_DATABASE_URL)
	@test -n "$(m)" || (echo 'Укажите описание: make migration m="..."'; exit 1)
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: clean
clean: ## Удалить .venv и кэши
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
