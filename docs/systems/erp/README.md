# ERP (бэк-офис) — `apps/erp`
Статус: действует · Владелец: лид · Обновлено: 2026-10-29

Домен бэк-офиса: каталог, расчёт, КП, договор, счёт, акт, оплаты, исполнение, склад, закупки; портальный API для Cabinet и
интеграционный API для CRM. Django · DRF · Celery · Channels; фронтенд React + shadcn/Tailwind заморожен и отключается задачей P6 волны 18a после гейтов D1-7 и D2-6 (DECISIONS 2026-10-27, 2026-10-28).
Выделена из B2B в M1 (история — тег `b2b-final`). Правила кода — [`CONVENTIONS.md`](CONVENTIONS.md); runbook'и —
[`docs/runbooks/erp/`](../../runbooks/erp/README.md); границы домена — стратегия 2026-10-23 §3.3, ADR-0015.

## Команды

```
make check-erp                      # из корня = make -C apps/erp check: lint + typecheck + i18n + vitest + pytest
make -C apps/erp install            # линтеры бэкенда (uv venv .venv-tools) и npm ci фронтенда
make -C apps/erp lint               # flake8, black, isort, eslint, tsc, симметрия i18n
make -C apps/erp test-backend       # pytest в контейнере на одноразовых Postgres 17 + Redis (scripts/test_backend_local.sh)
make -C apps/erp test-frontend      # vitest
make -C apps/erp openapi            # backend/schema.json + frontend/src/api/schema.d.ts
make -C apps/erp migrate|shell|createsuperuser|seed   # на стенде ансамбля (erp-backend)
```

## Стенд

ERP поднимается только корневым `make up` (`infra/compose`): `erp-backend` (Daphne), `erp-worker`, `erp-worker-ai`,
`erp-beat`, `erp-web` (nginx со сборкой Vite). Домен `http://erp.localhost`: `/api`, `/admin`, `/ws`, `/static`,
`/media`, `/health` → бэкенд, остальное → SPA. База `erp` на общем PostgreSQL 17; Redis два (S0-2): `redis-broker` БД 1 (Celery) и 2 (Channels), `redis-cache` БД 0 (кэш).
Файлы — в RustFS (бакеты `erp-private`, `erp-public`, `erp-temp`; S0-1). Первый суперпользователь:
`make -C apps/erp createsuperuser`; демо-справочники: `make -C apps/erp seed`.

## Что сделано и что дальше

Здесь не ведётся: журнал задач и PR — `docs/PROGRESS.md`, где мы и что дальше — `docs/HANDOFF.md`, хвосты — `docs/BACKLOG.md`.
