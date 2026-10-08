"""Задача Procrastinate: ингест документа базы знаний (PLAN Фаза 1)."""

from procrastinate import RetryStrategy

from app.container import get_container
from app.services.kb.ingest import KbIngestService
from app.tasks.queue import queue


def build_ingest_service() -> KbIngestService:
    c = get_container()
    return KbIngestService(
        c.session_factory, c.storage, c.docling, c.embedder, c.settings.s3_bucket_kb
    )


@queue.task(
    name="ingest_kb_document",
    queue="ingest",
    retry=RetryStrategy(max_attempts=3, exponential_wait=10),
)
async def ingest_kb_document(document_id: int, force: bool = False) -> int:
    return await build_ingest_service().ingest(document_id, force=force)


async def enqueue_ingest(document_id: int, *, force: bool = False) -> int:
    """Ставит ингест; повторная постановка того же документа не дублируется."""
    deferrer = ingest_kb_document.configure(
        lock=f"kb-document-{document_id}", queueing_lock=f"kb-document-{document_id}"
    )
    job_id: int = await deferrer.defer_async(document_id=document_id, force=force)
    return job_id
