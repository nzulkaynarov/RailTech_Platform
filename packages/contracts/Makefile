# packages/contracts — проверка контракта и генерация клиентов (ORCHESTRATOR §3.3: контракт раньше кода).
# Вызывается из корня: make contracts. CI после make contracts требует чистый git diff в generated/.
SHELL := /bin/bash
.DEFAULT_GOAL := check

.PHONY: install
install: ## Зависимости генераторов (pnpm, lockfile)
	pnpm install --frozen-lockfile

.PHONY: lint
lint: install ## Линт OpenAPI (redocly), валидация схемы событий и описания erp-mcp (ajv)
	pnpm lint

.PHONY: generate
generate: install ## TS-типы (openapi-typescript) для трёх пространств и fetch-клиент Integration API для CRM (orval)
	pnpm generate

.PHONY: check
check: lint generate typecheck ## Всё вместе

.PHONY: clean
clean:
	rm -rf node_modules

.PHONY: typecheck
typecheck: install ## tsc по сгенерированным типам и клиенту
	pnpm typecheck
