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
openapi: ## Экспорт OpenAPI internal (schema.json) и типы фронтенда — в контейнере, как api-contract в CI B2B
	./scripts/test_backend_local.sh --openapi
	cd $(FRONTEND) && npm run gen:api-types

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
