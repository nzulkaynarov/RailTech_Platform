# RailTech Platform — корневой Makefile ансамбля (CLAUDE.md, ORCHESTRATOR §4, §7).
# Цели ансамбля делегируют в Makefile приложений: конвенции и команды живут у приложений.
# Ветка `legacy/b2b` ни одной целью не проверяется и не собирается (ORCHESTRATOR §3.11).

SHELL := /bin/bash
.DEFAULT_GOAL := help

CRM     := apps/crm
ERP     := apps/erp
CABINET := apps/cabinet
INFRA   := infra

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Проверки --------------------------------------------------------------------

.PHONY: check
check: check-crm check-erp check-cabinet ## Проверки всех приложений (lint + typecheck + unit)

.PHONY: check-crm
check-crm: ## CRM: ruff, mypy, eslint, tsc, pytest, vitest (apps/crm/Makefile)
	$(MAKE) -C $(CRM) check

.PHONY: check-erp
check-erp: ## ERP: появится с M1-ERP-01; пока кода нет — пропуск
	@if [ -f $(ERP)/Makefile ]; then $(MAKE) -C $(ERP) check; else echo "check-erp: $(ERP) ещё без кода (M1-ERP-01) — пропуск"; fi

.PHONY: check-cabinet
check-cabinet: ## Cabinet: появится с M2-CAB-01; пока кода нет — пропуск
	@if [ -f $(CABINET)/Makefile ]; then $(MAKE) -C $(CABINET) check; else echo "check-cabinet: $(CABINET) ещё без кода (M2-CAB-01) — пропуск"; fi

.PHONY: tokens
tokens: ## Токены дизайна: tokens.json → dist/ и apps/crm/frontend/src/app/tokens.generated.ts (M0-INF-05)
	$(MAKE) -C packages/ui-tokens build

.PHONY: contracts
contracts: ## Валидация packages/contracts и генерация клиентов (M0-INF-02)
	@if [ -f packages/contracts/Makefile ]; then $(MAKE) -C packages/contracts check; else echo "contracts: packages/contracts ещё не заполнен (M0-INF-02)"; exit 1; fi

# --- Стенд ансамбля: три домена *.localhost (infra/compose, M0-INF-03) ---------------

COMPOSE := docker compose -f $(INFRA)/compose/base.yml -f $(INFRA)/compose/dev.yml --env-file .env
HTTP_PORT ?= $(shell grep -E '^HTTP_PORT=' .env 2>/dev/null | cut -d= -f2)

.PHONY: env
env: ## Создать .env из .env.example со случайными секретами (идемпотентно)
	./$(INFRA)/compose/make-env.sh

.PHONY: up
up: _compose-check ## Поднять весь ансамбль локально: crm.localhost, erp.localhost, cabinet.localhost
	$(COMPOSE) up -d --build --renew-anon-volumes

.PHONY: up-obs
up-obs: _compose-check ## То же + Langfuse (профиль observability): langfuse.localhost
	$(COMPOSE) --profile observability up -d --build --renew-anon-volumes

.PHONY: smoke
smoke: ## /health трёх доменов через Caddy (порт HTTP_PORT из .env)
	@port=$${HTTP_PORT:-$(or $(HTTP_PORT),80)}; ok=1; \
	for host in crm erp cabinet; do \
	  code=$$(curl -sL -o /dev/null -w '%{http_code}' --resolve $$host.localhost:$$port:127.0.0.1 http://$$host.localhost:$$port/health); \
	  printf '  %-18s /health → %s\n' $$host.localhost $$code; [ "$$code" = 200 ] || ok=0; \
	done; [ $$ok = 1 ] && echo "smoke: ok" || { echo "smoke: FAIL"; exit 1; }

.PHONY: down
down: _compose-check ## Остановить стенд ансамбля (volumes сохраняются)
	$(COMPOSE) --profile observability down

.PHONY: logs
logs: _compose-check ## Логи стенда: make logs s=erp
	$(COMPOSE) logs -f --tail=200 $(s)

.PHONY: ps
ps: _compose-check ## Статус контейнеров стенда
	$(COMPOSE) ps

.PHONY: _compose-check
_compose-check:
	@test -f .env || { echo "Нет .env: выполните make env (создаст из .env.example)"; exit 1; }

# --- Локальный CI (гейт мержа, пока GitHub Actions недоступен — DECISIONS 2026-10-13) ---

.PHONY: ci-local
ci-local: ## Те же задания, что .github/workflows/ci.yml, на этом компьютере: make ci-local [args="--quick"]
	./scripts/ci_local.sh $(args)

# --- Хуки --------------------------------------------------------------------------

.PHONY: hooks
hooks: ## Установить pre-commit-хуки корня (gitleaks и быстрые проверки)
	pre-commit install
