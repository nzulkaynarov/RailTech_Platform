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
	cd $(BACKEND) && uv run mypy app tests evals promptfoo alembic
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
eval: ## ПЛАТНО (реальные модели, ~150 вызовов): полный golden. make eval CONFIRM=yes [EVAL_MAX_USD=1]
	@$(MAKE) --no-print-directory _paid-check
	mkdir -p backend/evals/reports
	$(COMPOSE) run --rm -e EVAL_MAX_USD=$(or $(EVAL_MAX_USD),1) -v "$(CURDIR)/backend/evals/reports:/app/evals/reports" worker pytest -m eval evals -p no:cacheprovider -s

.PHONY: eval-quick
eval-quick: ## ПЛАТНО, ~20 вызовов: 12 ключевых кейсов. make eval-quick CONFIRM=yes [EVAL_MAX_USD=0.3]
	@$(MAKE) --no-print-directory _paid-check
	mkdir -p backend/evals/reports
	$(COMPOSE) run --rm -e EVAL_MAX_USD=$(or $(EVAL_MAX_USD),0.3) -e EVAL_CASES=$(QUICK_CASES) -v "$(CURDIR)/backend/evals/reports:/app/evals/reports" worker pytest -m eval evals -p no:cacheprovider -s

QUICK_CASES := kb-ru-pos-timeline,kb-uz-track-install,kb-en-track-packages,not-in-kb-ru-weather,injection-ru-inside-kb-question,human-ru-operator,customer-contract-july-ru,customer-change-terms,price-without-kb,price-quoted-from-price-list,researcher-early,info-geography

.PHONY: _paid-check
_paid-check:
	@test "$(CONFIRM)" = "yes" || { echo "⚠️  Цель вызывает ПЛАТНЫЕ модели (ключи из .env). Подтвердите: CONFIRM=yes. Потолок расходов — EVAL_MAX_USD."; exit 1; }

.PHONY: promptfoo
PROMPTFOO_VERSION := 0.124.1
promptfoo: ## ПЛАТНО: матрица промпт × модель через LiteLLM dev-стенда. CONFIRM=yes, LITELLM_API_KEY = LITELLM_MASTER_KEY
	@$(MAKE) --no-print-directory _paid-check
	@test -n "$$LITELLM_API_KEY" || { echo "Задайте LITELLM_API_KEY (значение LITELLM_MASTER_KEY из .env)"; exit 1; }
	cd $(BACKEND) && PYTHONPATH=. PROMPTFOO_PYTHON="$$(uv run python -c 'import sys; print(sys.executable)')" \
		PROMPTFOO_LITELLM_URL="$${PROMPTFOO_LITELLM_URL:-http://localhost:4000/v1}" \
		npx -y promptfoo@$(PROMPTFOO_VERSION) eval -c promptfoo/promptfooconfig.yaml --no-cache

.PHONY: openapi
openapi: ## Экспорт OpenAPI → docs/api/openapi.json и генерация клиента orval (frontend/src/api/generated)
	cd $(BACKEND) && PYTHONPATH=. uv run python ../scripts/export_openapi.py ../docs/api/openapi.json
	cd $(FRONTEND) && pnpm api:generate

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

.PHONY: load-test
load-test: ## Нагрузочный smoke: 50 параллельных диалогов, p95 ≤ 6 с (реальные модели, ADR-0014)
	$(COMPOSE) run --rm worker python -m app load-test --yes $(args)

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
seed: ## Демо-лиды и менеджер manager@demo.local: make seed pass=<пароль ≥10, буквы+цифры>
	@test -n "$(pass)" || (echo "Укажите пароль демо-менеджера: make seed pass=..."; exit 1)
	$(COMPOSE) run --rm api python -m app seed-demo --manager-password '$(pass)'

.PHONY: create-admin
create-admin: ## Первый администратор: make create-admin email=admin@railtech.uz name="Имя"
	@test -n "$(email)" || (echo "Укажите email: make create-admin email=..."; exit 1)
	$(COMPOSE) run --rm api python -m app create-admin --email '$(email)' --name '$(or $(name),Администратор)'

.PHONY: settings
settings: ## Настройки: make settings key=notifications [value='{"channel_id": -100123}']
	$(COMPOSE) run --rm --no-deps api python -m app settings '$(or $(key),all)' $(if $(value),'$(value)',)

.PHONY: test-e2e-local
test-e2e-local: ## E2E Playwright против запущенного стенда (BASE_URL=http://localhost)
	cd $(FRONTEND) && BASE_URL=$(or $(BASE_URL),http://localhost) pnpm e2e

.PHONY: smoke-dev
smoke-dev: ## Smoke-проверка dev-стенда (/health, /ready)
	./scripts/smoke_dev.sh

# --- prod (Фаза 8) ------------------------------------------------------------------

.PHONY: up-prod
up-prod: ## Поднять prod-стенд из образов GHCR (IMAGE_TAG в .env; на VPS)
	$(COMPOSE_PROD) --profile backup pull
	$(COMPOSE_PROD) --profile backup up -d --remove-orphans

.PHONY: smoke-prod
smoke-prod: ## Smoke-проверка prod: TLS, /ready, заголовки, закрытый API (DOMAIN из .env)
	./scripts/smoke_prod.sh

.PHONY: backup
backup: ## Внеочередной бэкап dev (prod: scripts/backup.sh --prod)
	./scripts/backup.sh

.PHONY: restore
restore: ## Восстановить dev из бэкапа: make restore b=latest (prod: scripts/restore.sh --prod)
	./scripts/restore.sh $(or $(b),latest)
