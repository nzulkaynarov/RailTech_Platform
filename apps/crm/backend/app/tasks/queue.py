"""Приложение Procrastinate: очередь и планировщик на PostgreSQL (ADR-0006).

Задачи — в модулях `TASK_MODULES`; воркер импортирует их при старте.
Схема Procrastinate применяется миграцией Alembic, не CLI.
"""

import procrastinate

from app.config import get_settings

TASK_MODULES = (
    "app.tasks.ingest",
    "app.tasks.qualify",
    "app.tasks.timers",
    "app.tasks.notify",
    "app.tasks.reports",
    "app.tasks.documents",
    "app.tasks.monitoring",
    "app.tasks.mail",
    "app.tasks.external_services",
    "app.tasks.erp_events",
    "app.tasks.erp_users",
)

queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().libpq_dsn),
    import_paths=TASK_MODULES,
)
