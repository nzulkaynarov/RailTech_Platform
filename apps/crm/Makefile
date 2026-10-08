# RailTech CRM — команды разработки и эксплуатации (CLAUDE.md §3).
# Docker-цели (up/down/logs/migrate/seed/smoke/backup) запускает человек на стенде;
# check/test/openapi — где угодно, без Docker.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend
COMPOSE_BASE := docker compose -f infra/docker-compose.yml --env-file .env
COMPOSE      := $(COMPOSE_BASE) -f infra/docker-compose.dev.yml
COMPOSE_PROD := $(COMPOSE_BASE) -f infra/docker-compose.prod.yml

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Зависимости ---------------------------------------------------------------

.PHONY: install
install: ## Установить зависимости backend (uv) и frontend (pnpm)
	cd $(BACKEND) && uv sync --frozen
	cd $(FRONTEND) && pnpm install --frozen-lockfile

.PHONY: clean
clean: ## Удалить .venv, node_modules и кэши (единственный разрешённый способ rm -rf)
	rm -rf $(BACKEND)/.venv $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache $(BACKEND)/.pytest_cache
	rm -rf $(FRONTEND)/node_modules $(FRONTEND)/dist $(FRONTEND)/coverage

# --- Качество (без Docker) -----------------------------------------------------

.PHONY: lint
lint: ## ruff + eslint + prettier --check
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .
	cd $(FRONTEND) && pnpm lint && pnpm format:check

.PHONY: typecheck
typecheck: ## mypy + tsc
	cd $(BACKEND) && uv run mypy app tests alembic
	cd $(FRONTEND) && pnpm typecheck

.PHONY: test
test: ## Unit-тесты backend (pytest) и frontend (vitest)
	cd $(BACKEND) && uv run pytest
	cd $(FRONTEND) && pnpm test

.PHONY: check
check: lint typecheck test ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: test-int
test-int: ## Integration-тесты (нужны Postgres+pgvector и RustFS; см. CI)
	cd $(BACKEND) && uv run pytest -m integration

.PHONY: test-e2e
test-e2e: ## E2E-тесты (появляются с Фазы 4)
	cd $(BACKEND) && uv run pytest -m e2e

.PHONY: eval
eval: ## Evals качества ИИ (нужны ключи моделей; с Фазы 2)
	cd $(BACKEND) && uv run pytest -m eval

.PHONY: promptfoo
promptfoo: ## Матрица промпт × модель (Фаза 7)
	@echo "promptfoo появится в Фазе 7 (PLAN.md)"; exit 1

.PHONY: openapi
openapi: ## Экспорт OpenAPI → docs/api/openapi.json (генерация клиента orval — Фаза 4)
	cd $(BACKEND) && PYTHONPATH=. uv run python ../scripts/export_openapi.py ../docs/api/openapi.json

.PHONY: migration
migration: ## Создать миграцию: make migration m="add leads"
	@test -n "$(m)" || (echo 'Укажите описание: make migration m="..."'; exit 1)
	cd $(BACKEND) && uv run alembic revision --autogenerate -m "$(m)"

# --- dev-стенд (Docker, запускает человек) ----------------------------------------

.PHONY: up
up: ## Поднять dev-стенд (без Langfuse)
	$(COMPOSE) up -d --build

.PHONY: up-obs
up-obs: ## Поднять dev-стенд с Langfuse (профиль observability)
	$(COMPOSE) --profile observability up -d --build

.PHONY: down
down: ## Остановить dev-стенд (данные в volumes сохраняются)
	$(COMPOSE) --profile observability down

.PHONY: logs
logs: ## Логи dev-стенда: make logs s=api
	$(COMPOSE) logs -f --tail=200 $(s)

.PHONY: ps
ps: ## Статус контейнеров dev-стенда
	$(COMPOSE) ps

.PHONY: migrate
migrate: ## Применить миграции Alembic на dev-стенде
	$(COMPOSE) run --rm migrate

.PHONY: kb-demo
kb-demo: ## Загрузить демо-базу знаний (нужны ключи моделей в .env)
	$(COMPOSE) run --rm worker python -m app kb-demo

.PHONY: kb-eval
kb-eval: ## Проверить поиск на демо-KB: top-3 ≥ 13/15, uz ≥ 3/4 (гейт Фазы 1)
	$(COMPOSE) run --rm worker python -m app kb-eval

.PHONY: kb-ingest
kb-ingest: ## Загрузить файл в KB: make kb-ingest f=path/to/file.pdf lang=ru product=pos-integration
	@test -n "$(f)" || (echo 'Укажите файл: make kb-ingest f=...'; exit 1)
	$(COMPOSE) run --rm -v "$(abspath $(f)):/import/$(notdir $(f)):ro" worker \
		python -m app kb-ingest "/import/$(notdir $(f))" --language $(or $(lang),ru) $(if $(product),--product $(product)) --sync

.PHONY: seed
seed: ## Демо-данные (Фаза 2+)
	@echo "scripts/seed_demo.py появится в Фазе 2 (PLAN.md)"; exit 1

.PHONY: smoke-dev
smoke-dev: ## Smoke-проверка dev-стенда (/health, /ready)
	./scripts/smoke_dev.sh

# --- prod (Фаза 8) ------------------------------------------------------------------

.PHONY: up-prod
up-prod: ## Поднять prod-стенд (на VPS)
	$(COMPOSE_PROD) up -d

.PHONY: smoke-prod
smoke-prod: ## Smoke-проверка prod (Фаза 8)
	@echo "scripts/smoke_prod.sh появится в Фазе 8 (PLAN.md)"; exit 1

.PHONY: backup
backup: ## Бэкап Postgres + S3/RustFS (Фаза 8)
	@echo "scripts/backup.sh появится в Фазе 8 (PLAN.md)"; exit 1

.PHONY: restore
restore: ## Восстановление из бэкапа (Фаза 8)
	@echo "scripts/restore.sh появится в Фазе 8 (PLAN.md)"; exit 1
