.PHONY: up down logs shell migrate makemigrations createsuperuser seed test test-backend test-frontend lint lint-backend lint-frontend build clean format security collectstatic celery-logs frontend-shell

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
i18n-check:
	@docker compose exec -T backend sh -c "cp locale/en/LC_MESSAGES/django.po /tmp/before.po && \
		python manage.py makemessages -l en --ignore=migrations --ignore=venv --ignore=node_modules --ignore=staticfiles >/dev/null 2>&1 && \
		diff <(grep -v '^\"POT-Creation-Date' /tmp/before.po) <(grep -v '^\"POT-Creation-Date' locale/en/LC_MESSAGES/django.po) >/dev/null \
		&& echo 'i18n catalog: up to date' || (echo 'i18n catalog STALE — run make i18n-extract and translate new strings' && cp /tmp/before.po locale/en/LC_MESSAGES/django.po && exit 1)"

lint: lint-backend lint-frontend

lint-backend:
	docker compose exec backend bash -c "flake8 . && black --check . && isort --check-only ."

lint-frontend:
	docker compose exec frontend npm run lint

# Build commands
build:
	docker compose build

# Cleanup
clean:
	docker compose down -v
	docker system prune -f

# Code formatting
format:
	docker compose exec backend bash -c "black . && isort ."

# Security checks
security:
	docker compose exec backend bash -c "pip audit || true"
	docker compose exec frontend bash -c "npm audit || true"

# Static files
collectstatic:
	docker compose exec backend python manage.py collectstatic --noinput

# Celery logs
celery-logs:
	docker compose logs -f celery-worker

# Frontend shell
frontend-shell:
	docker compose exec frontend bash
