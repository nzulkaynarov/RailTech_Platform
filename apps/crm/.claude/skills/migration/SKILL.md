---
name: migration
description: Создать Alembic-миграцию по изменению SQLAlchemy-моделей, реализовать и проверить downgrade, синхронизировать SPEC §5.
---

# Миграция

Правила (CLAUDE.md §4): одна миграция на PR; обратимая; имя файла `YYYYMMDD_HHMM_slug` (задано в `backend/alembic.ini`, проверяется тестом `tests/unit/test_migrations_conventions.py`).

## Шаги

1. Измени модели в `backend/app/models/` (наследники `app.models.base.Base`; имена ограничений — из `NAMING_CONVENTION`). Таблицы — с `created_at`, `updated_at` (`SPEC §5`).
2. Если в PR уже есть миграция — дополни её, а не создавай вторую.
3. Создание: `make migration m="add leads"` (autogenerate через контейнер api стенда). Без стенда — ревизия вручную: `cd backend && uv run alembic revision -m "add leads"`.
4. Прочитай сгенерированный файл целиком: autogenerate не видит расширения, триггеры, `GENERATED`-колонки, HNSW/GIN-индексы, ENUM — допиши руками.
5. `downgrade()` — полный откат в обратном порядке (тест падает на пустом `downgrade`).
6. Таблицы Procrastinate/LangGraph не трогай: они исключены из autogenerate (`alembic/env.py`). Обновление Procrastinate — отдельная ревизия, применяющая SQL из `procrastinate/sql/migrations` (ADR-0006).
7. Проверка:
   - `make check`;
   - integration-тест upgrade → downgrade → upgrade (`tests/integration/test_migrations.py`) — расширь проверку новыми объектами; прогоняется в CI; локально — только на одноразовом контейнере (`scripts/test_int_local.sh -k migrations`, скилл `stand-verify`), **никогда** на БД стенда;
   - на стенде: `make migrate` → без ошибок, `/ready` 200.
8. Сверь `SPEC §5`: если схема расходится — это отклонение от SPEC → вопрос человеку, затем правка SPEC/ADR. Новая настройка (`settings.<key>`) миграции не требует — скилл `settings-key`.
9. Prod: миграции не откатываются автоматически, правило expand → contract (runbook `deploy.md`); перед выкладкой — бэкап.
10. В PR, раздел «Проверить на dev»: `make migrate` → без ошибок; `make down && make up` → `/ready` 200.
