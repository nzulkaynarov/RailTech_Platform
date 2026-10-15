# apps/erp — ERP (бэк-офис). Копия B2B (M1-ERP-01); команды — те же проверки, что были в legacy/b2b,
# но без привязки к стенду: бэкенд-тесты идут на одноразовых контейнерах (scripts/test_backend_local.sh),
# линтеры — в локальном venv версий CI, фронтенд — npm на хосте. Вызывается из корня: make check-erp.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend
# Пины линтеров = CI (black>=24,<25, isort>=5,<6, flake8). uv создаёт venv быстро и без системного pip.
TOOLS_VENV := .venv-tools
TOOLS_BIN  := $(TOOLS_VENV)/bin
TOOLS_PINS := flake8 black>=24,<25 isort>=5,<6
TOOLS_STAMP := $(TOOLS_VENV)/.pins

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Зависимости -----------------------------------------------------------------

.PHONY: install
install: $(TOOLS_STAMP) ## Линтеры бэкенда (uv venv) и зависимости фронтенда (npm ci)
	cd $(FRONTEND) && npm ci --legacy-peer-deps

$(TOOLS_STAMP):
	rm -rf $(TOOLS_VENV)
	uv venv -q $(TOOLS_VENV)
	uv pip install -q --python $(TOOLS_BIN)/python $(foreach pin,$(TOOLS_PINS),"$(pin)")
	@printf '%s\n' "$(TOOLS_PINS)" > $(TOOLS_STAMP)

.PHONY: clean
clean: ## Удалить venv линтеров, node_modules и сборки
	rm -rf $(TOOLS_VENV) $(FRONTEND)/node_modules $(FRONTEND)/dist $(BACKEND)/htmlcov $(BACKEND)/.pytest_cache

# --- Качество ----------------------------------------------------------------------

.PHONY: lint-backend
lint-backend: $(TOOLS_STAMP) ## flake8 + black --check + isort --check (из apps/erp, чтобы читался .flake8)
	$(TOOLS_BIN)/flake8 $(BACKEND)/
	$(TOOLS_BIN)/black --check $(BACKEND)/
	$(TOOLS_BIN)/isort --check-only $(BACKEND)/

.PHONY: format
format: $(TOOLS_STAMP) ## black + isort
	$(TOOLS_BIN)/black $(BACKEND)/
	$(TOOLS_BIN)/isort $(BACKEND)/

.PHONY: lint-frontend
lint-frontend: ## eslint
	cd $(FRONTEND) && npm run lint

.PHONY: typecheck
typecheck: ## tsc -b
	cd $(FRONTEND) && npm run lint:tsc

.PHONY: i18n-check
i18n-check: ## Симметрия ru.json / en.json
	python3 scripts/check_i18n_symmetry.py

.PHONY: lint
lint: lint-backend lint-frontend typecheck i18n-check ## Все линтеры

.PHONY: test-frontend
test-frontend: ## vitest
	cd $(FRONTEND) && npm run test

.PHONY: test-backend
test-backend: ## pytest в контейнере на одноразовых Postgres 17 + Redis (как CI B2B): make test-backend args="-k quotes"
	./scripts/test_backend_local.sh $(args)

.PHONY: test
test: test-frontend test-backend ## Все тесты

.PHONY: check
check: lint test ## Всё — обязательно перед PR (make check-erp из корня)

.PHONY: openapi
openapi: ## Экспорт OpenAPI internal (schema.json), типы фронтенда и экспорт в packages/contracts (M1-ERP-10)
	./scripts/test_backend_local.sh --openapi
	cd $(FRONTEND) && npm run gen:api-types
	cp $(BACKEND)/schema.json ../../packages/contracts/openapi/erp-internal-full.json

# --- Стенд ансамбля ---------------------------------------------------------------------
# ERP поднимается только через корневой make up (infra/compose): erp.localhost. Здесь — обёртки.

.PHONY: migrate
migrate: ## Миграции на стенде ансамбля
	cd ../.. && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py migrate --noinput

.PHONY: shell
shell: ## Django shell на стенде ансамбля
	cd ../.. && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py shell

.PHONY: createsuperuser
createsuperuser: ## Суперпользователь ERP на стенде
	cd ../.. && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py createsuperuser

.PHONY: seed
seed: ## dev/demo-справочники и тест-пользователи (core_seed) на стенде
	cd ../.. && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py core_seed

# --- ИИ (M1-ERP-06): состояние шлюза и evals ----------------------------------------------
STAND := cd ../.. && docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env

.PHONY: ai-status
ai-status: ## Состояние ИИ ERP без вызова моделей: шлюз, бюджет и расход за сегодня, ошибки, версии промптов
	$(STAND) exec erp-backend python manage.py ai_status

.PHONY: ai-gateway-sync
ai-gateway-sync: ## Перерегистрировать ключ ERP в LiteLLM (бюджет на день, трейсы Langfuse) после правки .env
	$(STAND) run --rm erp-ai-gateway

# Ключевые кейсы eval-quick (~10 вызовов intake-model/match-model). Полный набор — make eval.
QUICK_CASES := text-two-goods-ru,text-cable-meters,text-latin-translit,text-service,text-not-a-request,csv-simple-table,exact-name-ru,latin-to-cyrillic,code-is-the-strong-signal,nothing-fits

.PHONY: eval-quick
eval-quick: ## ПЛАТНО (~10 вызовов): ключевые golden-кейсы разбора и сопоставления. make eval-quick CONFIRM=yes [EVAL_MAX_USD=0.2]
	@$(MAKE) --no-print-directory _paid-check
	$(STAND) run --rm --no-deps -e EVAL_CONFIRM=yes -e EVAL_MAX_USD=$(or $(EVAL_MAX_USD),0.2) -e EVAL_CASES=$(QUICK_CASES) erp-worker-ai pytest -m eval evals -p no:cacheprovider -s

.PHONY: eval
eval: ## ПЛАТНО (~20 вызовов): все golden-кейсы ERP. make eval CONFIRM=yes [EVAL_MAX_USD=0.5]
	@$(MAKE) --no-print-directory _paid-check
	$(STAND) run --rm --no-deps -e EVAL_CONFIRM=yes -e EVAL_MAX_USD=$(or $(EVAL_MAX_USD),0.5) erp-worker-ai pytest -m eval evals -p no:cacheprovider -s

.PHONY: _paid-check
_paid-check:
	@test "$(CONFIRM)" = "yes" || { echo "Цель вызывает ПЛАТНЫЕ модели через LiteLLM стенда — только с согласия владельца на этот прогон. Подтвердите: CONFIRM=yes. Потолок — EVAL_MAX_USD."; exit 1; }
