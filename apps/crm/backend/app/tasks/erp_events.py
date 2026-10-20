"""Фоновые задачи событий ERP (M3-CRM-04, FIX-33): обработка и сборщик зависших."""

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued

from app.container import get_container
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=3, wait=10)


@queue.task(name="process_erp_event", queue="notify", retry=RETRY)
async def process_erp_event(event_id: str) -> bool:
    return await get_container().erp_events_service.process_event(event_id)


@queue.periodic(cron="* * * * *", periodic_id="erp_events_sweep")
@queue.task(name="erp_events_sweep", queue="notify", queueing_lock="erp_events_sweep")
async def erp_events_sweep(timestamp: int) -> int:
    """Раз в минуту: `received` без задачи в очереди и неотправленные сообщения."""
    return await get_container().erp_events_service.sweep()


def event_lock(event_id: str) -> str:
    return f"erp_event:{event_id}"


async def enqueue_erp_event(event_id: str) -> int | None:
    """Поставить обработку события; `None` — задача на него уже ждёт в очереди."""
    try:
        job_id: int = await process_erp_event.configure(
            queueing_lock=event_lock(event_id)
        ).defer_async(event_id=event_id)
    except AlreadyEnqueued:
        return None
    return job_id
