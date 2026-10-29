---
name: db-migration
description: Миграция схемы базы в любом домене RailTech Platform — Alembic (EDS; для CRM — подробный скилл apps/crm migration), Django (ERP, миграция rt-bus) — одна обратимая миграция на PR, id от генератора, разрешение двух голов или листьев после merge origin/main, проверка на одноразовой базе.
---

# Миграция

Общие правила — ORCHESTRATOR §4.1 «Миграции»: номер не бронируется, существующие ревизии не переименовываются, две головы
или конфликт листьев ловит CI и разрешает ветка, пришедшая второй. Своя база у каждого домена — чужие таблицы не трогать
(§3 п. 2 и 16).

## CRM (Alembic)

Подробно — скилл `apps/crm/.claude/skills/migration` (autogenerate через стенд, ручные объекты, Procrastinate, SPEC §5).

## EDS (Alembic)

1. Правила — `docs/systems/eds/CONVENTIONS.md`: одна голова (`test_single_head`), обратимая, имя `YYYYMMDD_HHMM_slug`,
   `revision` — выданный Alembic.
2. `make -C apps/eds migration m="…"` (нужна база по `EDS_DATABASE_URL`); без базы — `cd apps/eds && uv run alembic revision -m "…"`
   и операции вручную.
3. Прочитай файл целиком, допиши `downgrade()`.
4. Проверка — `make -C apps/eds test` (одноразовый `postgres:17`: миграции вверх и вниз).
5. Две головы после merge `origin/main` — `uv run alembic merge heads -m "merge"` или свой `down_revision` на новую голову.

## ERP (Django)

1. Правила — `docs/systems/erp/CONVENTIONS.md` («Параллельные миграции»).
2. Создание — в контейнере тестов: `ERP_TEST_NS=<задача> apps/erp/scripts/test_backend_local.sh --manage makemigrations <app>`.
3. Проверка схемы — `ERP_TEST_NS=<задача> apps/erp/scripts/test_backend_local.sh --migration-check`
   (`makemigrations --check` и `migrate` на чистой базе; в CI — задание `erp-schema`).
4. Конфликт листьев после merge `origin/main` — `--manage makemigrations --merge` или `dependencies` своей миграции на новый
   лист. Одинаковый номер в имени файла у разных миграций допустим.
5. После — `apps/erp/scripts/test_backend_local.sh --down`.

## rt-bus (Django-миграция таблиц шины)

`make -C packages/rt-bus migrations-check` (без базы) и `make -C packages/rt-bus test`. Изменение таблиц шины задевает все
домены — задание `rt-bus` и потребители (скилл `pre-pr`).

## Прод

Миграции применяются при деплое и автоматически не откатываются: расширение схемы — сначала, сужение — отдельным PR после
выкладки (`docs/runbooks/deploy.md`).
