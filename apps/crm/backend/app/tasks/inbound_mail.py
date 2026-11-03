"""Опрос общего ящика (W18A-P2, B-INB-5): раз в 2 минуты, одна задача одновременно.

`queueing_lock` + `lock`: письма не забираются дважды параллельно (дубль ловит ещё и UNIQUE
`message_id`). Подсказку помощника задача не запрашивает — только кнопка «Подсказать» в карточке
письма (решение юриста 2026-11-02).
"""

from app.container import get_container
from app.tasks.queue import queue


@queue.periodic(cron="*/2 * * * *", periodic_id="inbound_mail_poll")
@queue.task(
    name="inbound_mail_poll",
    queue="timers",
    queueing_lock="inbound_mail_poll",
    lock="inbound_mail_poll",
)
async def inbound_mail_poll(timestamp: int) -> str:
    return (await get_container().inbound_mail_ingest.poll()).status


@queue.task(
    name="inbound_mail_history",
    queue="ingest",
    queueing_lock="inbound_mail_history",
    lock="inbound_mail_history",
)
async def inbound_mail_history(import_id: int) -> str:
    """«Загрузить письма за период» (W18A-P2-2): одна загрузка одновременно."""
    return await get_container().inbound_mail_history.run(import_id)


async def enqueue_history(import_id: int) -> object:
    return await inbound_mail_history.defer_async(import_id=import_id)
