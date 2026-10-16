"""Фоновая задача обработки событий ERP (M3-CRM-04)."""

from procrastinate import RetryStrategy

from app.container import get_container
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=3, wait=10)


@queue.task(name="process_erp_event", queue="notify", retry=RETRY)
async def process_erp_event(event_id: str) -> bool:
    return await get_container().erp_events_service.process_event(event_id)


async def enqueue_erp_event(event_id: str) -> int:
    job_id: int = await process_erp_event.defer_async(event_id=event_id)
    return job_id
