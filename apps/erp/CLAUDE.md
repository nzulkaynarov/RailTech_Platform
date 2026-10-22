# CLAUDE.md — `apps/erp` (указатель)

ERP — домен бэк-офиса: каталог, расчёт, КП, договор, счёт, акт, оплаты, исполнение, склад, портальный и интеграционный API. Django · DRF · Celery. Фронтенд `frontend/` заморожен и удаляется на этапе C2.

**Прочитай:** `docs/systems/erp/CONVENTIONS.md` (правила кода; в коде ссылки `CONVENTIONS.md §N` ведут туда) и
`docs/ORCHESTRATOR.md` (процесс, инварианты, протокол сессии); правило среды, тестов и CI — `CLAUDE.md` корня.
Запуск и устройство — `docs/systems/erp/README.md`. Runbook'и — `docs/runbooks/erp/`. Промпты ИИ (`backend/prompts/`) живут здесь — их читает код.

Документация — только в `docs/` (ORCHESTRATOR §3 п. 17): здесь новых `.md` не заводить.

Главные команды:

- `make -C apps/erp install` — линтеры бэкенда и npm ci
- `make check-erp` из корня — lint, typecheck, i18n, vitest, pytest
- `ERP_TEST_NS=<задача> make -C apps/erp test-backend args="<app>/tests/<файл>.py -x -q"` — один тест
- `make -C apps/erp openapi` / `openapi-check` — схема и `erp-internal.yaml`
