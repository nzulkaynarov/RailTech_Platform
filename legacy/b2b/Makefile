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

# Database commands (external Neon Cloud DB — migrations run via backend container)
migrate:
	docker compose exec backend python manage.py migrate

makemigrations:
	docker compose exec backend python manage.py makemigrations

createsuperuser:
	docker compose exec backend python manage.py createsuperuser

seed:
	docker compose exec backend python manage.py loaddata seed_data

# Testing commands
test:
	docker compose exec backend pytest

test-backend:
	docker compose exec backend pytest --cov=. --cov-report=html

test-frontend:
	docker compose exec frontend npm test

# Linting commands
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
