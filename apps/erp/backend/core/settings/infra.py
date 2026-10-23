"""Кэш и Celery (очереди default/pdf/imports/ai — ARCH-01). Два экземпляра Redis (S0-2, ADR-0013 п. 5, ADR-0017):
`redis-cache` — кэш Django, троттлинг, одноразовые jti; `redis-broker` — брокер и результаты Celery, Channels."""

import os

from .api import *  # noqa: F401,F403 — последовательная композиция настроек

# Кэш — `redis-cache` (volatile-lru, у всех ключей есть срок: TIMEOUT ниже и явные `timeout=` в коде). Отказ кэша не роняет ERP:
# `core.cache.ResilientRedisCache` отвечает «пусто» и пишет предупреждение; одноразовые jti и коды 2FA идут через
# `core.cache.fail_closed()` и при отказе дают 503 с понятным текстом, а не пропуск. Короткие таймауты — чтобы зависший
# (не отказавший) Redis не держал запросы.
CACHES = {
    "default": {
        "BACKEND": "core.cache.ResilientRedisCache",
        "LOCATION": os.environ.get("REDIS_CACHE_URL", "redis://redis-cache:6379/0"),
        "TIMEOUT": 300,
        "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
    }
}

# Celery — `redis-broker` (appendonly yes, noeviction): очередь и результаты не должны теряться при рестарте и вытесняться.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis-broker:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis-broker:6379/1")
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
