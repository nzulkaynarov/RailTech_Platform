# apps/cabinet — Cabinet (кабинет клиента): SPA без бэкенда, ходит в ERP /api/portal/v1 (ADR-0004).
# Из корня: make check-cabinet → make -C apps/cabinet check. Зависимости — npm ci по package-lock.json.
SHELL := /bin/bash
.DEFAULT_GOAL := help

TOKENS_DST := src/styles/tokens.generated.css

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Зависимости (npm ci)
	npm ci

.PHONY: lint
lint: ## eslint (семантические токены, правила React Compiler)
	npm run lint -- --max-warnings=0

.PHONY: typecheck
typecheck: ## tsc -b
	npm run typecheck

.PHONY: i18n-check
i18n-check: ## Симметрия ru / uz / en, дубли ключей, кириллица в латинских локалях, t() без ключа
	python3 scripts/check_i18n_symmetry.py

.PHONY: tokens-check
tokens-check: ## Копия токенов совпадает с генерацией из packages/ui-tokens/tokens.json (dist/ не коммитится — собираем)
	@$(MAKE) --no-print-directory -C ../../packages/ui-tokens check >/dev/null \
	  || { echo "cabinet: $(TOKENS_DST) или другие копии токенов устарели — выполните make tokens из корня"; exit 1; }
	@echo "tokens: ok"

.PHONY: api-types-check
api-types-check: ## Типы совпадают с генерацией: портал (erp-portal.yaml) и форма лида CRM (apps/crm/docs/api/openapi.json)
	@npx openapi-typescript ../../packages/contracts/openapi/erp-portal.yaml 2>/dev/null | diff -q - src/api/portal.d.ts >/dev/null \
	  || { echo "cabinet: src/api/portal.d.ts устарел — выполните make -C apps/cabinet gen-api-types"; exit 1; }
	@node scripts/gen-crm-form-types.mjs | diff -q - src/api/crm-form.d.ts >/dev/null \
	  || { echo "cabinet: src/api/crm-form.d.ts устарел (OpenAPI CRM) — выполните make -C apps/cabinet gen-api-types"; exit 1; }
	@echo "api types: ok"

.PHONY: test
test: ## Vitest + Testing Library + axe (мок портального API на msw/node)
	npm run test

.PHONY: check
check: lint typecheck i18n-check tokens-check api-types-check test ## Всё — обязательно перед PR (make check-cabinet из корня)

.PHONY: dev
dev: ## Vite dev-сервер на :5175 с моком портального API (VITE_PORTAL_MOCK=1)
	VITE_PORTAL_MOCK=1 npx vite --port 5175 --strictPort

.PHONY: dev-stand
dev-stand: ## Vite dev-сервер на :5175 без мока: /api/portal → стенд ERP (VITE_PORTAL_PROXY_TARGET), форма лида → CRM (VITE_CRM_PROXY_TARGET)
	VITE_PORTAL_MOCK=0 npx vite --port 5175 --strictPort

.PHONY: build
build: ## Прод-сборка статики в dist/
	npm run build

.PHONY: gen-api-types
gen-api-types: ## Типы портала (erp-portal.yaml → src/api/portal.d.ts) и формы лида CRM (→ src/api/crm-form.d.ts)
	npm run gen:api-types

.PHONY: clean
clean: ## Удалить node_modules и сборку
	rm -rf node_modules dist coverage
