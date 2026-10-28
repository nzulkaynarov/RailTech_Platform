# rt-docs — документы: тело JSON → HTML → PDF (WeasyPrint), DOCX, форматтеры (docs/architecture/rt-docs.md, ADR-0020).
# Инструменты — как packages/rt-bus: uv, ruff, mypy, pytest. Рендер PDF — в одноразовом контейнере (pango, harfbuzz):
# scripts/in_container.sh, образ docker/test.Dockerfile (базовый — по digest) — один и тот же локально и в CI (job rt-docs).

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help
help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Зависимости (uv sync --frozen)
	uv sync --frozen

.PHONY: lint
lint: ## ruff check + ruff format --check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: typecheck
typecheck: ## mypy --strict
	uv run mypy rt_docs tests scripts

.PHONY: test-unit
test-unit: ## Тесты без рендера PDF — на этой машине, без Docker (схема, HTML, DOCX, импорт, форматтеры, шрифты)
	uv run pytest --ignore=tests/pdf

.PHONY: test
test: ## Все тесты, включая эталонные PDF — в контейнере (сеть выключена); args="…" — аргументы pytest
	./scripts/in_container.sh pytest -p no:cacheprovider $(args)

.PHONY: check
check: lint typecheck test ## Всё вышеперечисленное — обязательно перед коммитом

.PHONY: image-rm
image-rm: ## Удалить образы тестов rt-docs-test:* этой машины
	-docker images --format '{{.Repository}}:{{.Tag}}' | grep '^rt-docs-test:' | xargs -r docker rmi

.PHONY: clean
clean: ## Удалить .venv и кэши
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
