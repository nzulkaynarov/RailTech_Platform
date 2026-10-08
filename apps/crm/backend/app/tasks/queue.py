"""Приложение Procrastinate: очередь и планировщик на PostgreSQL (ADR-0006).

Задачи регистрируются в модулях `app/tasks/*` начиная с Фазы 1.
Схема Procrastinate применяется миграцией Alembic, не CLI.
"""

import procrastinate

from app.config import get_settings

queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().libpq_dsn),
)
