"""Приложение Procrastinate: очередь и планировщик на PostgreSQL сервиса (как в CRM, ADR-0006).

Задачи — в модулях `TASK_MODULES`; воркер импортирует их при старте. Схема Procrastinate применяется
миграцией Alembic `0001_init`, не CLI.
"""

import procrastinate

from app.config import get_settings
from app.tasks.policy import enforce_timeout

TASK_MODULES = (
    "app.tasks.bus",
    "app.tasks.maintenance",
    "app.tasks.renders",
    "app.tasks.stalled",
)

queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().libpq_dsn),
    import_paths=TASK_MODULES,
    # Предельное время задачи (ЗАВИС-1): зависший вызов не оставляет задачу в `doing` навсегда.
    worker_defaults={"worker_middleware": [enforce_timeout]},
)
