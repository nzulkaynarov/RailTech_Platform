"""Периодические задачи Procrastinate. Cron — в UTC (Ташкент = UTC+5, без DST)."""

from datetime import UTC, datetime

from app.container import get_container
from app.services.timers import mark_unresponsive
from app.tasks.queue import queue


@queue.periodic(cron="17 * * * *", periodic_id="unresponsive")
@queue.task(name="mark_unresponsive", queue="timers", queueing_lock="mark_unresponsive")
async def mark_unresponsive_task(timestamp: int) -> int:
    c = get_container()
    return await mark_unresponsive(
        c.session_factory, c.settings_service, datetime.fromtimestamp(timestamp, UTC)
    )
