# ERP (бэк-офис) — `apps/erp`
Статус: действует · Владелец: лид · Обновлено: 2026-10-29

Домен бэк-офиса: каталог, расчёт, КП, договор, счёт, акт, оплаты, исполнение, склад, закупки; портальный API для Cabinet и
интеграционный API для CRM. Django · DRF · Celery · Channels; своего фронтенда нет (удалён 2026-11-11): интерфейс сотрудников — Платформа, клиента — Cabinet.
Выделена из B2B в M1 (история — тег `b2b-final`). Правила кода — [`CONVENTIONS.md`](CONVENTIONS.md); runbook'и —
[`docs/runbooks/erp/`](../../runbooks/erp/README.md); границы домена — стратегия 2026-10-23 §3.3, ADR-0015.

## Команды

```
make check-erp                      # из корня = make -C apps/erp check: lint + pytest
make -C apps/erp install            # линтеры бэкенда (uv venv .venv-tools)
make -C apps/erp lint               # flake8, black, isort
make -C apps/erp test-backend       # pytest в контейнере на одноразовых Postgres 17 + Redis (scripts/test_backend_local.sh)
make -C apps/erp openapi            # backend/schema.json + packages/contracts/openapi/erp-internal.yaml
make -C apps/erp migrate|shell|createsuperuser|seed   # на стенде ансамбля (erp-backend)
```

## Стенд

ERP поднимается только корневым `make up` (`infra/compose`): `erp-backend` (Daphne), `erp-worker`, `erp-worker-ai`,
`erp-beat`. Домен `http://erp.localhost`: `/api`, `/ws`, `/static`,
`/media`, `/health` → бэкенд, остальное — 302 в Платформу. База `erp` на общем PostgreSQL 17; Redis два (S0-2): `redis-broker` БД 1 (Celery) и 2 (Channels), `redis-cache` БД 0 (кэш).
Файлы — в RustFS (бакеты `erp-private`, `erp-public`, `erp-temp`; S0-1). Первый суперпользователь:
`make -C apps/erp createsuperuser`; демо-справочники: `make -C apps/erp seed`.

## Что сделано и что дальше

Здесь не ведётся: журнал задач и PR — `docs/PROGRESS.md`, где мы и что дальше — `docs/HANDOFF.md`, хвосты — `docs/BACKLOG.md`.
