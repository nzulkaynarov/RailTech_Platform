"""Приложение Procrastinate: очередь и планировщик на PostgreSQL сервиса (как в CRM, ADR-0006).

Задачи — в модулях `TASK_MODULES`; воркер импортирует их при старте. Схема Procrastinate применяется
миграцией Alembic `0001_init`, не CLI.
"""

import procrastinate

from app.config import get_settings

TASK_MODULES = (
    "app.tasks.bus",
    "app.tasks.maintenance",
)

queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().libpq_dsn),
    import_paths=TASK_MODULES,
)
