# RailTech Platform — корневой Makefile ансамбля (CLAUDE.md, docs/ORCHESTRATOR.md §4, §7).
# Цели ансамбля делегируют в Makefile приложений: конвенции и команды живут у приложений.
# Директория legacy/b2b удалена по плану M2-INF-01; исходная история сохранена в теге b2b-final.

SHELL := /bin/bash
.DEFAULT_GOAL := help

CRM     := apps/crm
ERP     := apps/erp
CABINET := apps/cabinet
PLATFORM := apps/platform
EDS     := apps/eds
INFRA   := infra

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Проверки --------------------------------------------------------------------

.PHONY: check
check: docs-links check-crm check-erp check-cabinet check-platform check-eds check-rt-bus check-rt-docs ## Проверки всех приложений, rt-bus, rt-docs (lint + typecheck + тесты) и ссылок документации

.PHONY: docs-links
docs-links: ## Ссылки на документацию целы и ведут в docs/, ID строк BACKLOG уникальны (scripts/check-doc-links.sh, ORCHESTRATOR §3 п. 17)
	scripts/check-doc-links.sh

.PHONY: docs-backlog
docs-backlog: ## Сводка docs/BACKLOG.md: всего, по приоритету и типу (счётчики в файле руками не ведутся — scripts/backlog.py)
	python3 scripts/backlog.py

.PHONY: check-crm
check-crm: ## CRM: ruff, mypy, eslint, tsc, pytest, vitest (apps/crm/Makefile)
	$(MAKE) -C $(CRM) check

.PHONY: check-erp
check-erp: ## ERP: появится с M1-ERP-01; пока кода нет — пропуск
	@if [ -f $(ERP)/Makefile ]; then $(MAKE) -C $(ERP) check; else echo "check-erp: $(ERP) ещё без кода (M1-ERP-01) — пропуск"; fi

.PHONY: check-cabinet
check-cabinet: ## Cabinet: eslint, tsc, i18n ru/uz/en, токены, типы портала, vitest + axe (apps/cabinet/Makefile)
	@if [ -f $(CABINET)/Makefile ]; then $(MAKE) -C $(CABINET) check; else echo "check-cabinet: $(CABINET) ещё без кода (M2-CAB-01) — пропуск"; fi

.PHONY: check-platform
check-platform: ## Платформа: ruff, mypy, pytest (bff); eslint, tsc, vitest, свежесть клиента orval, токенов, RBAC и моделей CRM из crm.yaml (apps/platform/Makefile)
	$(MAKE) -C $(PLATFORM) check

.PHONY: check-eds
check-eds: ## EDS: ruff, mypy --strict, pytest на PostgreSQL — миграции, шина, вход, права (apps/eds/Makefile; без EDS_TEST_DATABASE_URL — одноразовый postgres:17 в Docker)
	$(MAKE) -C $(EDS) check

.PHONY: check-rt-bus
check-rt-bus: ## Библиотека шины: ruff, mypy, миграция Django, pytest на PostgreSQL (packages/rt-bus/Makefile; без RT_BUS_TEST_DATABASE_URL — одноразовый postgres:17 в Docker)
	$(MAKE) -C packages/rt-bus check

.PHONY: check-rt-docs
check-rt-docs: ## Документы (rt-docs): ruff, mypy, pytest с эталонными PDF в одноразовом контейнере (packages/rt-docs/Makefile; docker/test.Dockerfile, сеть выключена)
	$(MAKE) -C packages/rt-docs check

.PHONY: tokens
tokens: ## Токены дизайна: tokens.json → dist/, копии в apps/crm (tokens.generated.ts), apps/cabinet (tokens.generated.css), apps/platform (tokens.generated.ts)
	$(MAKE) -C packages/ui-tokens build
	$(MAKE) -C $(PLATFORM) tokens

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
smoke: ## /health доменов CRM, ERP, Cabinet и Платформы (+ / Платформы), 404 на /api/integration и /admin ERP — через Caddy (порт HTTP_PORT из .env)
	@port=$${HTTP_PORT:-$(or $(HTTP_PORT),80)}; ok=1; \
	for host in crm erp cabinet; do \
	  code=$$(curl -sL -o /dev/null -w '%{http_code}' --resolve $$host.localhost:$$port:127.0.0.1 http://$$host.localhost:$$port/health); \
	  printf '  %-18s /health → %s\n' $$host.localhost $$code; [ "$$code" = 200 ] || ok=0; \
	done; \
	code=$$(curl -sL -o /dev/null -w '%{http_code}' --resolve platform.localhost:$$port:127.0.0.1 http://platform.localhost:$$port/api/v1/health); \
	printf '  %-18s /api/v1/health → %s\n' platform.localhost $$code; [ "$$code" = 200 ] || ok=0; \
	code=$$(curl -sL -o /dev/null -w '%{http_code}' --resolve platform.localhost:$$port:127.0.0.1 http://platform.localhost:$$port/); \
	printf '  %-18s / → %s\n' platform.localhost $$code; [ "$$code" = 200 ] || ok=0; \
	for path in /api/integration/v1/health /admin/; do \
	  code=$$(curl -s -o /dev/null -w '%{http_code}' --resolve erp.localhost:$$port:127.0.0.1 http://erp.localhost:$$port$$path); \
	  printf '  %-18s %s → %s (ожидается 404)\n' erp.localhost $$path $$code; [ "$$code" = 404 ] || ok=0; \
	done; \
	[ $$ok = 1 ] && echo "smoke: ok" || { echo "smoke: FAIL"; exit 1; }

.PHONY: caddy-reload
caddy-reload: _compose-check ## Пересоздать Caddy после правки infra/caddy/Caddyfile.dev (bind-mount файла не видит замену файла git'ом)
	$(COMPOSE) up -d --force-recreate --no-deps caddy

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

# --- Прод на двух VPS (infra/compose/prod.yml + db.yml, M5-INF-01; runbook docs/runbooks/deploy.md) ---------
# Выполняется на VPS 1 из каталога релиза: /opt/rt/releases/<тег>. Деплой обычно ведёт .github/workflows/deploy.yml.

PROD_ENV ?= /opt/rt/.env.prod
COMPOSE_PROD := docker compose -f $(INFRA)/compose/base.yml -f $(INFRA)/compose/prod.yml --env-file $(PROD_ENV)

.PHONY: up-prod
up-prod: ## Прод (VPS 1): up образов тега RT_IMAGE_TAG без миграций и дампа; штатно — infra/deploy/deploy.sh <тег>
	@test -f $(PROD_ENV) || { echo "Нет $(PROD_ENV): infra/deploy/make-env-prod.sh init"; exit 1; }
	@test -n "$(RT_IMAGE_TAG)" || { echo "Задайте RT_IMAGE_TAG=<git sha>"; exit 1; }
	RT_IMAGE_TAG=$(RT_IMAGE_TAG) $(COMPOSE_PROD) up -d --remove-orphans

.PHONY: deploy-check
deploy-check: ## Проверка конфигурации прода без запуска: compose prod/db, Caddyfile.prod, shellcheck, actionlint (одноразовые контейнеры)
	@set -e; export RT_IMAGE_TAG=$${RT_IMAGE_TAG:-deploy-check}; envfile=$$(mktemp); trap 'rm -f $$envfile' EXIT; sed 's/CHANGE_ME/ci-only-value/' $(INFRA)/.env.prod.example >$$envfile; \
	docker compose -f $(INFRA)/compose/base.yml -f $(INFRA)/compose/prod.yml --env-file $$envfile --profile observability --profile kb-ingest --profile mcp config -q; \
	docker compose -f $(INFRA)/compose/db.yml --env-file $$envfile config -q; echo "compose prod/db: ok"
	@docker run --rm -e ACME_EMAIL=a@example.com -e CRM_DOMAIN=crm.example.org -e ERP_DOMAIN=erp.example.org -e CABINET_DOMAIN=cabinet.example.org -e PLATFORM_DOMAIN=platform.example.org 	  -v "$(CURDIR)/$(INFRA)/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" caddy:2.11.7-alpine caddy validate --config /etc/caddy/Caddyfile 2>&1 | grep -q "Valid configuration" && echo "caddy validate: ok"
	@docker run --rm -e LANG=C.UTF-8 -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:stable -x $(INFRA)/deploy/*.sh $(INFRA)/db/*.sh $(INFRA)/s3/*.sh scripts/qemu_cpu_check.sh && echo "shellcheck: ok"
	@bash $(INFRA)/deploy/tests/predeploy-dump-test.sh
	@bash $(INFRA)/deploy/tests/reset-prod-test.sh
	@bash $(INFRA)/deploy/tests/bus-contracts-image-test.sh
	@bash $(INFRA)/deploy/tests/crm-backup-source-test.sh
	@bash $(INFRA)/deploy/tests/crm-status-sources-test.sh
	@bash $(INFRA)/deploy/tests/telegram-webhook-url-test.sh
	@bash $(INFRA)/deploy/tests/crm-bot-test.sh
	@bash $(INFRA)/deploy/tests/cpu-baseline-test.sh
	@scripts/qemu_cpu_check.sh all --skip-missing
	@bash $(INFRA)/deploy/tests/platform-prod-test.sh
	@bash $(INFRA)/deploy/tests/platform-bus-test.sh
	@bash $(INFRA)/deploy/tests/caddy-edge-test.sh
	@bash $(INFRA)/deploy/tests/wal-archive-test.sh
	@bash $(INFRA)/deploy/tests/walg-schedule-test.sh
	@bash $(INFRA)/deploy/tests/redis-split-test.sh
	@bash $(INFRA)/deploy/tests/s3-keys-test.sh
	@bash $(INFRA)/deploy/tests/eds-prod-test.sh
	@bash $(INFRA)/deploy/tests/retry-test.sh
	@bash $(INFRA)/deploy/tests/should-deploy-test.sh
	@docker run --rm -v "$(CURDIR):/repo" -w /repo rhysd/actionlint:latest .github/workflows/deploy.yml && echo "actionlint: ok"

# --- Локальный CI (гейт мержа, пока GitHub Actions недоступен — DECISIONS 2026-10-13) ---

.PHONY: cpu-check
cpu-check: ## Старт образов прода под CPU qemu64 (S0-7): собрать linux/amd64, проверить, удалить; make cpu-check [args="rt-litellm"] (на Mac arm64 долго)
	@scripts/qemu_cpu_check.sh run $(args)

.PHONY: cpu-selftest
cpu-selftest: ## Механика qemu64 ловит реальное: Wolfi и numpy 2.4+ падают, numpy<2.4 проходит
	@scripts/qemu_cpu_check.sh selftest

.PHONY: ci-local
ci-local: ## Те же задания, что .github/workflows/ci.yml, на этом компьютере: make ci-local [args="--quick"]
	./scripts/ci_local.sh $(args)

# --- Хуки --------------------------------------------------------------------------

.PHONY: hooks
hooks: ## Установить pre-commit-хуки корня (gitleaks и быстрые проверки)
	pre-commit install
