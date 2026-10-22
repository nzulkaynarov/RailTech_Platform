# Платформа (SPA + BFF) — команды разработки (docs/systems/platform/CONVENTIONS.md §3).
# Всё, кроме Docker-целей, работает без Docker: web (pnpm) и bff (uv).

SHELL := /bin/bash
.DEFAULT_GOAL := help

WEB := web
BFF := bff
TOKENS := ../../packages/ui-tokens

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Зависимости ---------------------------------------------------------------

.PHONY: install
install: ## Установить зависимости bff (uv) и web (pnpm)
	cd $(BFF) && uv sync --frozen
	cd $(WEB) && pnpm install --frozen-lockfile

.PHONY: clean
clean: ## Удалить .venv, node_modules, сборку и кэши
	rm -rf $(BFF)/.venv $(BFF)/.mypy_cache $(BFF)/.ruff_cache $(BFF)/.pytest_cache
	rm -rf $(WEB)/node_modules $(WEB)/dist $(WEB)/coverage $(WEB)/test-results $(WEB)/playwright-report

# --- Генерация -------------------------------------------------------------------

.PHONY: gen-api
gen-api: ## Клиент, типы и MSW-моки web из packages/contracts/openapi/platform-bff.yaml (orval)
	cd $(WEB) && pnpm gen:api

.PHONY: api-check
api-check: gen-api ## Сгенерированный клиент свеж: после gen-api нет диффа в web/src/shared/api/generated
	git diff --exit-code -- $(WEB)/src/shared/api/generated \
	  || { echo "Клиент orval устарел — make -C apps/platform gen-api и закоммитьте"; exit 1; }
	@test -z "$$(git ls-files --others --exclude-standard -- $(WEB)/src/shared/api/generated)" \
	  || { echo "Клиент orval: появились неотслеживаемые файлы — закоммитьте результат make gen-api"; exit 1; }

# Токены: копия dist/antd.ts лежит в приложении, чтобы образ web собирался с контекстом apps/platform/web.
# build.mjs пакета ui-tokens не знает про Платформу, поэтому копию делает этот Makefile
# (флаги --no-* не трогают сгенерированные файлы CRM, Cabinet и ERP).
.PHONY: tokens
tokens: ## packages/ui-tokens → web/src/app/tokens.generated.ts
	node $(TOKENS)/build.mjs --no-crm --no-cabinet --no-erp
	cp $(TOKENS)/dist/antd.ts $(WEB)/src/app/tokens.generated.ts

.PHONY: tokens-check
tokens-check: ## Копия токенов совпадает с packages/ui-tokens
	node $(TOKENS)/build.mjs --no-crm --no-cabinet --no-erp >/dev/null
	cmp -s $(TOKENS)/dist/antd.ts $(WEB)/src/app/tokens.generated.ts \
	  || { echo "tokens.generated.ts устарел — make -C apps/platform tokens и закоммитьте"; exit 1; }

# RBAC: матрица ролей, меню и поля с ограничением — из packages/contracts/platform-rbac.yaml (PLT-11).
# Генератор лежит в scripts/ и запускается в окружении bff (pyyaml, jsonschema).
.PHONY: rbac
rbac: ## packages/contracts/platform-rbac.yaml → bff/app/rbac_generated.py и web/src/app/rbac.generated.ts
	cd $(BFF) && uv run python ../scripts/gen_rbac.py

.PHONY: rbac-check
rbac-check: ## Сгенерированные файлы RBAC совпадают с контрактом
	cd $(BFF) && uv run python ../scripts/gen_rbac.py --check

# --- Качество (без Docker) ---------------------------------------------------------

.PHONY: lint
lint: ## ruff + eslint + prettier --check
	cd $(BFF) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB) && pnpm lint && pnpm format:check

.PHONY: typecheck
typecheck: ## mypy (strict) + tsc
	cd $(BFF) && uv run mypy app tests
	cd $(WEB) && pnpm typecheck

.PHONY: test
test: ## pytest (bff) и vitest (web)
	cd $(BFF) && uv run pytest
	cd $(WEB) && pnpm test

.PHONY: check
check: lint typecheck test api-check tokens-check rbac-check ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: e2e
e2e: ## Playwright + axe на MSW (поднимает vite --mode mock на :4173, порт — переменная E2E_PORT); браузеры: pnpm exec playwright install chromium
	cd $(WEB) && pnpm e2e

# --- Образы (Docker, локальная проверка сборки) ----------------------------------------

.PHONY: docker-build
docker-build: ## Собрать prod-образы bff и web (теги rt-platform-bff / rt-platform-web, TAG=local)
	docker build --target prod -t rt-platform-bff:$(or $(TAG),local) $(BFF)
	docker build --target prod -t rt-platform-web:$(or $(TAG),local) $(WEB)
