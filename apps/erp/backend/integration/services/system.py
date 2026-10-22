"""System services for CRM integration: AI usage aggregation and health checks (M3-ERP-01)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Tuple

from django.conf import settings
from django.db import connection
from django.db.models import Count, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_ai_usage_rows(date_from: date, date_to: date) -> List[Dict[str, Any]]:
    """Агрегирует расходы ERP на ИИ по дням, функциям и моделям."""
    try:
        from ai.models import AICall

        qs = (
            AICall.objects.filter(
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
            )
            .values("created_at__date", "feature", "model_alias")
            .annotate(
                calls=Count("id"),
                input_tokens=Sum("input_tokens"),
                output_tokens=Sum("output_tokens"),
                total_cost=Sum("cost_usd"),
            )
            .order_by("created_at__date", "feature", "model_alias")
        )

        rows = []
        for r in qs:
            cost = r["total_cost"] or 0
            rows.append(
                {
                    "date": r["created_at__date"].isoformat(),
                    "system": "erp",
                    "feature": r["feature"] or "unknown",
                    "model": r["model_alias"] or "default",
                    "calls": r["calls"],
                    "input_tokens": r["input_tokens"] or 0,
                    "output_tokens": r["output_tokens"] or 0,
                    "cost_usd": f"{cost:.6f}",
                }
            )
        return rows
    except Exception as exc:
        logger.warning("Error fetching AI usage: %s", exc)
        return []


def get_system_health() -> Tuple[Dict[str, Any], int]:
    """Проверка здоровья ERP: статус базы, неприменённые миграции и состояние очереди."""
    migrations_applied = True
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        unapplied = executor.migration_plan(targets)
        migrations_applied = len(unapplied) == 0
    except Exception as exc:
        logger.warning("Error checking migrations: %s", exc)
        migrations_applied = False

    # «Очередь жива» = брокер Celery (`redis-broker`) отвечает. Кэш (`redis-cache`) сюда не входит: его отказ ERP переживает
    # (core.cache), и 503 здоровья из-за него заставил бы CRM считать рабочий ERP мёртвым (S0-2).
    queue_alive = True
    try:
        from core.celery import app as celery_app

        with celery_app.connection_for_read() as broker_connection:
            broker_connection.ensure_connection(max_retries=1, interval_start=0, timeout=2)
    except Exception as exc:  # noqa: BLE001 — любая ошибка брокера = очередь не жива, проверка здоровья не падает
        logger.warning("Error checking queue (broker): %s", type(exc).__name__)
        queue_alive = False

    status_str = "ok" if (migrations_applied and queue_alive) else "degraded"
    http_status = 200 if status_str == "ok" else 503

    health = {
        "status": status_str,
        "version": getattr(settings, "ERP_VERSION", "0.1.0"),
        "migrations_applied": migrations_applied,
        "queue_alive": queue_alive,
        "checked_at": timezone.now().isoformat(),
    }
    # M3-ERP-06: внешние сервисы ERP по журналам и счётчикам (без обращений к сервисам). Поле необязательное —
    # без миграций или кэша его просто нет, а `/health` по-прежнему отвечает.
    if migrations_applied:
        try:
            from .externals import build_externals

            health["externals"] = build_externals()
        except Exception as exc:  # noqa: BLE001 — внешние сервисы не должны ронять проверку здоровья
            logger.warning("Error building externals: %s", exc)
    return health, http_status
