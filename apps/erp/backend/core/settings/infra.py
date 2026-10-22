"""Кэш и Celery (очереди default/pdf/imports/ai — ARCH-01)."""

import os

from .api import *  # noqa: F401,F403 — последовательная композиция настроек

# Cache (Redis — already running for Channels)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        "TIMEOUT": 300,
    }
}

# Celery Configuration Options
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Queue routing. TWO worker services consume the queues (see docker-compose[.prod].yml):
# `celery-worker` runs `-Q default,pdf,imports` and `celery-worker-ai` runs `-Q ai` —
# a DEDICATED process, because queue names alone give no isolation: on one shared worker
# two 30-min Excel imports would occupy every slot and starve interactive AI jobs past the
# frontend's 150s poll budget. Celery's built-in default queue is "celery", which no worker
# consumes — so without this block every `.delay()` lands in an orphaned "celery" queue and
# silently never runs (Excel import dead-end + stale-quote/auto-invoice beat jobs never
# firing). Pin the default queue to one the main worker consumes, and route the heavy bulk
# imports to their own queue so a 50k-row import can't starve transactional tasks.
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "sourcing.tasks.process_excel_import": {"queue": "imports"},
    "sourcing.tasks.process_catalog_import": {"queue": "imports"},
    # Синхронизация ТН ВЭД — получасовая выгрузка с медленного tarif.customs.uz: ей место
    # рядом с bulk-импортами, а не в default-очереди транзакционных задач.
    "master_data.tasks.refresh_tnved_codes": {"queue": "imports"},
    # ARCH-01: interactive AI jobs (request-path LLM calls offloaded from DRF views) go to
    # the "ai" queue, consumed ONLY by the dedicated celery-worker-ai service (IO-bound
    # HTTP waits — a bulk import can never occupy the slots an interactive job needs).
    "sourcing.run_ai_job": {"queue": "ai"},
}

# Beat (django_celery_beat.DatabaseScheduler подхватывает записи при старте): периодические задачи шины rt_bus
# добавляет `core/celery.py` (rt_bus.contrib.celery.install); остальные сеются миграцией `core/0002` (`core/seeds/beat.py`).
