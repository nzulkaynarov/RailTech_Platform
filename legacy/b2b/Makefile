.PHONY: ci-local e2e-prod up down logs shell migrate makemigrations createsuperuser seed test test-backend test-frontend lint lint-backend lint-frontend typecheck tools-reset build clean format security security-backend security-frontend collectstatic celery-logs frontend-shell i18n-extract i18n-compile i18n-check

# Docker Compose commands
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Backend shell access
shell:
	docker compose exec backend bash

# Database commands (local dev: `db` container из docker-compose.override.yml;
# prod: DB-VPS через WireGuard — миграции всегда через backend-контейнер)
migrate:
	docker compose exec backend python manage.py migrate

makemigrations:
	docker compose exec backend python manage.py makemigrations

createsuperuser:
	docker compose exec backend python manage.py createsuperuser

# core_seed = dev/demo-справочники + тест-пользователи (SEED_USER_PASSWORD).
# Бизнес-коды создаются data-миграциями (IRON RULE 1), loaddata здесь не используется —
# seed_data.json имеет кастомный формат core_seed и loaddata его не читает.
seed:
	docker compose exec backend python manage.py core_seed

# Testing commands
test:
	docker compose exec backend pytest

test-backend:
	docker compose exec backend pytest --cov=. --cov-report=html

# vitest запускается на машине разработчика (frontend-контейнер — prod nginx-сборка без npm)
test-frontend:
	cd frontend && npm test

# Linting commands
# ── i18n (L0, spec-bilingual-ru-en) ──────────────────────────────────────────
# .po — исходник переводов, лежит в git и ревьюится. .mo — производный бинарник:
# генерируется здесь и при сборке образа, в git не попадает.
i18n-extract:
	docker compose exec backend python manage.py makemessages -l en \
		--ignore=migrations --ignore=venv --ignore=node_modules --ignore=staticfiles

i18n-compile:
	docker compose exec backend python manage.py compilemessages

# Гейт свежести: после правки строк каталог обязан быть перегенерирован. Падает, если
# makemessages меняет .po (кроме служебной строки POT-Creation-Date).
# ВНИМАНИЕ: только bash. В образе /bin/sh — это dash, где нет подстановки процессов
# `<(...)`: цель падала на РАЗБОРЕ строки (`sh: 1: Syntax error: "(" unexpected`), то
# есть сообщала «каталог устарел» независимо от каталога и не запускала makemessages.
i18n-check:
	@docker compose exec -T backend bash -c "cp locale/en/LC_MESSAGES/django.po /tmp/before.po && \
		python manage.py makemessages -l en --ignore=migrations --ignore=venv --ignore=node_modules --ignore=staticfiles >/dev/null 2>&1 && \
		diff <(grep -v '^\"POT-Creation-Date' /tmp/before.po) <(grep -v '^\"POT-Creation-Date' locale/en/LC_MESSAGES/django.po) >/dev/null \
		&& echo 'i18n catalog: up to date' || (echo 'i18n catalog STALE — run make i18n-extract and translate new strings' && cp /tmp/before.po locale/en/LC_MESSAGES/django.po && exit 1)"

lint: lint-backend lint-frontend

# Линтеров НЕТ в backend-контейнере: образ собран по requirements.txt (прод-лок),
# flake8/black/isort живут только в requirements-dev.txt. Прежняя цель звала их внутри
# контейнера и падала с "flake8: command not found" (Error 127) — `make lint` не проверял
# ни строчки. Ставим их ВЕРСИЯМИ CI в локальный venv и гоняем ИЗ КОРНЯ по backend/,
# как джоба backend-lint: только из корня подхватывается корневой .flake8 с
# per-file-ignores для core/settings/* (внутри контейнера виден backend/.flake8 без них,
# и F403/F405 сыпались бы ложняком).
TOOLS_VENV := .venv-tools
TOOLS_BIN := $(TOOLS_VENV)/bin
# Пины держим ОДНОЙ строкой и штампуем её в venv: цель зависит от файла-отпечатка, а не
# от самого бинарника, поэтому смена версии здесь (вслед за ci.yml) пересобирает venv
# САМА. Иначе гейт тихо расходится с CI: `make format` переписывает файлы старым black,
# `make lint` зелёный, а джоба backend-lint падает на форматировании.
TOOLS_PINS := flake8 black>=24,<25 isort>=5,<6
TOOLS_STAMP := $(TOOLS_VENV)/.pins

$(TOOLS_STAMP):
	rm -rf $(TOOLS_VENV)
	python3 -m venv $(TOOLS_VENV)
	$(TOOLS_BIN)/pip install -q --upgrade pip
	$(TOOLS_BIN)/pip install -q $(foreach pin,$(TOOLS_PINS),"$(pin)")
	@printf '%s\n' "$(TOOLS_PINS)" > $(TOOLS_STAMP)

# Пересобрать набор линтеров принудительно
tools-reset:
	rm -rf $(TOOLS_VENV)
	$(MAKE) $(TOOLS_STAMP)

# Отпечаток устарел (пины в Makefile поменялись) — пересобрать перед проверкой
_tools-check:
	@[ -f $(TOOLS_STAMP) ] && [ "$$(cat $(TOOLS_STAMP))" = "$(TOOLS_PINS)" ] \
		|| $(MAKE) --no-print-directory tools-reset

lint-backend: _tools-check
	$(TOOLS_BIN)/flake8 backend/
	$(TOOLS_BIN)/black --check backend/
	$(TOOLS_BIN)/isort --check-only backend/

# Фронтенд линтится НА ХОСТЕ, как и vitest: контейнер frontend — прод-сборка nginx,
# в нём нет ни npm, ни bash. До 2026-08-13 цель звала `docker compose exec frontend npm`
# и падала с "executable file not found", а `make lint` из-за этого никогда не доходил
# до eslint — красный фронт всплывал только на CI.
lint-frontend:
	cd frontend && npm run lint

# Проверка типов: eslint её НЕ делает, а на CI роняет джобу frontend-build.
typecheck:
	cd frontend && npm run lint:tsc

# Build commands
build:
	docker compose build

# Cleanup
clean:
	docker compose down -v
	docker system prune -f

# Code formatting — тем же набором, что и проверяет lint-backend (иначе форматируем
# одной версией black, а CI ругается другой).
format: _tools-check
	$(TOOLS_BIN)/black backend/
	$(TOOLS_BIN)/isort backend/

# Security checks — зеркало CI-джобы `security` (оба гейта ЖЁСТКИЕ).
# Было до 2026-08-13: `pip audit` (нет такой подкоманды pip — нужен отдельный пакет
# pip-audit) и `npm audit` в nginx-контейнере без npm; обе ошибки глотал `|| true`,
# поэтому цель ВСЕГДА рапортовала успех и не поймала ни одной уязвимости.
# Зеркало ВСЕХ джоб ci.yml на машине разработчика — протокол мержа при мёртвом CI
# (Docs/dev/ops/merge-without-ci.md). SKIP=deps-lock,docker-build / ONLY=api-contract —
# выборочно; таблица для тела PR ложится в .ci-local/report.md.
ci-local:
	bash scripts/ci_local.sh

# Prod-safe Playwright с машины разработчика — замена nightly e2e, который лежит вместе с
# GitHub-hosted раннерами. Read-only smoke (health, /register, /setup-password, сырые i18n-ключи);
# остальные спеки сами skip вне локального стека. Нужны @playwright/test + chromium
# (`npx playwright install chromium`). Гонять после каждого деплоя (merge-without-ci.md, шаг 6).
e2e-prod:
	cd frontend && E2E_BASE_URL=$${E2E_BASE_URL:-https://b2b.railtech.uz} npx playwright test --reporter=list

security: security-backend security-frontend

# pip-audit без аргументов проверяет установленное окружение, а оно в образе ==
# requirements.txt — ровно то, что аудитит CI. Пакета нет в локах (CI ставит его тем же
# ad-hoc `pip install`), поэтому доставляем на месте — но в ОДНОРАЗОВЫЙ контейнер
# (`run --rm`), а не в живой через `exec`: exec тянет в рабочее окружение весь хвост
# pip-audit (requests, rich, cachecontrol, cyclonedx-…), которого нет в проде, и тогда
# `import requests` работает локально вечно, а в свежесобранном прод-образе падает
# ModuleNotFoundError. `--no-deps` не поднимает redis/db — аудиту они не нужны.
# Сам pip обновляем первым: pip-audit аудитит и его, а базовый pip образа приносит свои
# advisories, топящие находки по НАШИМ зависимостям (тот же порядок, что в ci.yml).
# Зовём через `python -m pip_audit`: в образе USER=appuser, и консольный скрипт уезжает
# в ~/.local/bin мимо PATH.
security-backend:
	docker compose run --rm --no-deps backend sh -c "pip install -q --disable-pip-version-check --no-warn-script-location --upgrade pip pip-audit && python -m pip_audit"

# HARD-гейт CI — только прод-зависимости (`--omit=dev`): всё, что уезжает пользователю.
# Вторая строка повторяет аудит вместе с dev-цепочкой — она ИНФОРМАТИВНАЯ (префикс `-`
# в make игнорирует её код возврата), как неблокирующий шаг в ci.yml.
security-frontend:
	cd frontend && npm audit --omit=dev --audit-level=high
	-cd frontend && npm audit --audit-level=high

# Static files
collectstatic:
	docker compose exec backend python manage.py collectstatic --noinput

# Celery logs
celery-logs:
	docker compose logs -f celery-worker

# Frontend shell
frontend-shell:
	docker compose exec frontend bash
