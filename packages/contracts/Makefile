# packages/contracts — проверка контракта и генерация клиентов (ORCHESTRATOR §3.3: контракт раньше кода).
# Вызывается из корня: make contracts. CI после make contracts требует чистый git diff в generated/.
# Node (pnpm): OpenAPI, ajv, AsyncAPI, TS-клиенты. Python (uv, pyproject.toml + uv.lock): модели rt-contracts,
# тесты схем событий и подписок, совместимость с базой (CONTRACTS_BASE_REF, по умолчанию origin/main).
SHELL := /bin/bash
.DEFAULT_GOAL := check

UV_RUN := uv run --locked

.PHONY: install
install: ## Зависимости генераторов: pnpm (lockfile) и uv (uv.lock, Python 3.12)
	pnpm install --frozen-lockfile
	uv sync --locked

.PHONY: lint
lint: install ## Линт OpenAPI (redocly), ajv (старая схема событий, erp-mcp, Платформа), AsyncAPI (parser), ruff скриптов
	pnpm lint
	$(UV_RUN) ruff check scripts tests
	$(UV_RUN) ruff format --check scripts tests

.PHONY: generate
generate: install ## TS-типы и orval-клиент; модели Pydantic v2 событий → generated/python (rt-contracts)
	pnpm generate
	$(UV_RUN) python scripts/gen_python.py

.PHONY: test
test: install ## Схемы событий валидны, примеры проходят конверт и схему типа, AsyncAPI ↔ файлы, подписки, модели; правила L8
	$(UV_RUN) pytest

.PHONY: compat
compat: install ## Совместимость схем events/** и bus/subscriptions.schema.json с базой (L8)
	$(UV_RUN) python scripts/events_compat.py

.PHONY: check
check: lint generate typecheck test compat ## Всё вместе

.PHONY: clean
clean:
	rm -rf node_modules .venv

.PHONY: typecheck
typecheck: install ## tsc по сгенерированным типам и клиенту
	pnpm typecheck
