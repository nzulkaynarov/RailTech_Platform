"""Задачи входящей почты (W18A-P2, B-INB-5): опрос общего ящика и подсказка помощника.

Опрос — раз в 2 минуты, одна задача одновременно (`queueing_lock` + `lock`): письма не забираются
дважды параллельно (дубль ловит ещё и UNIQUE `message_id`). Подсказка — задача на письмо после
коммита опроса, одна в очереди на письмо; сбой модели — `unavailable`, без повторов (вызовы
платные).
"""

from procrastinate.exceptions import AlreadyEnqueued

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


@queue.task(name="inbound_mail_assist", queue="qualifier")
async def inbound_mail_assist(mail_id: int) -> str:
    return await get_container().inbound_mail_assist.suggest(mail_id)


async def enqueue_assist(mail_ids: list[int]) -> None:
    for mail_id in mail_ids:
        lock = f"inbound_mail_assist:{mail_id}"
        try:
            await inbound_mail_assist.configure(queueing_lock=lock).defer_async(mail_id=mail_id)
        except AlreadyEnqueued:
            continue
