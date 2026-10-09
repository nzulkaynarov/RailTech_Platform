"""Извлечение текста документов клиентов (docling) для поиска бота."""

from procrastinate import RetryStrategy

from app.container import get_container
from app.tasks.queue import queue


@queue.task(
    name="extract_document_text",
    queue="ingest",
    retry=RetryStrategy(max_attempts=3, exponential_wait=10),
)
async def extract_document_text(document_id: int) -> str:
    return await get_container().document_service.extract_text(document_id)
