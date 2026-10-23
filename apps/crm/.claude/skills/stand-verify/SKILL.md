---
name: stand-verify
description: Проверить изменения на локальном dev-стенде (Mac + Docker Desktop) — какие контейнеры перечитывают код, а какие надо перезапустить, smoke, integration-тесты на одноразовых контейнерах, настройки и платные вызовы.
---

# Проверка на локальном стенде

docs/systems/crm/CONVENTIONS.md писан для облака без Docker; на компьютере владельца Docker Desktop есть, и стенд — рабочий инструмент агента. Правила неизменны: платные вызовы моделей — только с согласия, integration-тесты — никогда на БД стенда, действия, которые пишут клиенту в Telegram, — не нажимать.

## Шаги

1. Состояние: `make ps`, `curl -s localhost:${DEV_API_PORT:-8000}/ready`, `make smoke-dev`. Порты — из `.env` (`DEV_API_PORT` и др.); CRM — `http://localhost` (или `HTTP_PORT`).
2. Код ветки на стенде: `api` (`--reload`) и `web` (vite с примонтированным исходником) подхватывают правки сами; `worker`, `crm-mcp`, `kb-mcp`, `docs-mcp` — нет: `docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file .env restart worker crm-mcp kb-mcp docs-mcp`. Новые зависимости или Dockerfile — `make up` (пересборка). Миграция — `make migrate`.
3. Проверка бэкенда: `backend/tests/integration` — только через `scripts/test_int_local.sh [-k маска]` (одноразовые Postgres+RustFS на 127.0.0.1:55432/59000, `env -i` без ключей стенда); после — `scripts/test_int_local.sh --down`.
4. Проверка фронта: скилл `ui-review` (скриншоты + axe на 1440/390), e2e — `make test-e2e-local BASE_URL=http://localhost` с `E2E_ADMIN_PASSWORD`/`E2E_MANAGER_PASSWORD` (учётки стенда; пароли не в git и не в чат).
5. Бот: диалог ведётся из своего Telegram с тестовым лидом; кнопки CRM «Ответить», «Вернуть боту» пишут реальному лиду — только на тестовых лидах (`make seed`). Канал команды — `make settings key=notifications`.
6. Настройки: сохранённый ключ перекрывает дефолты целиком — после смены дефолтов `make settings key=<key>` и при необходимости `reset=1` (скилл `settings-key`, runbook `dev-stand.md` п. 12).
7. Платные цели (`make eval*`, `make promptfoo`, `make load-test`, `make kb-demo` с реальными embeddings) — только после названной стоимости и явного «да» владельца на этот прогон.
8. Диагностика: `make logs s=api|worker|crm-mcp`; `bot_started`, `TelegramConflictError` (второй стенд с тем же токеном), `LlmUnavailableError` (кредиты/ключи) — runbook `dev-stand.md`, `bot-silent.md`.
9. В PR «Как проверено» — что именно прогнано на стенде (роли, размеры, тесты), а в «Проверить на dev» — что остаётся человеку (Telegram, платные прогоны, мерж).
