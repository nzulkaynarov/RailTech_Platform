# ERP (бэк-офис) — `apps/erp`
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

Домен бэк-офиса: каталог, расчёт, КП, договор, счёт, акт, оплаты, исполнение, склад, закупки; портальный API для Cabinet и
интеграционный API для CRM. Django · DRF · Celery · Channels; фронтенд React + shadcn/Tailwind заморожен и удаляется на этапе C2.
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
`/media`, `/health` → бэкенд, остальное → SPA. База `erp` на общем PostgreSQL 17, Redis БД 1 (Celery) и 2 (Channels, кэш).
Файлы — FileSystemStorage в томе `erp_media` (перевод на RustFS — отдельной задачей M1). Первый суперпользователь:
`make -C apps/erp createsuperuser`; демо-справочники: `make -C apps/erp seed`.

## Что ещё не сделано (по вехе M1)

Удаление слоёв маркетплейса/подписок/KYC/операторской плоскости (M1-ERP-02), новые имена приложений и свежие
миграции (M1-ERP-03), бренд в настройки (M1-ERP-04), роли бэк-офиса (M1-ERP-05), ИИ через LiteLLM (M1-ERP-06),
каталог с двумя слоями (M1-ERP-07), курс на дату КП (M1-ERP-08), настройки (M1-ERP-09), окончательный docs/systems/erp/CONVENTIONS.md,
OpenAPI в `packages/contracts`, runbook (M1-ERP-10). До M1-ERP-04 в UI и письмах остаётся бренд B2B.
