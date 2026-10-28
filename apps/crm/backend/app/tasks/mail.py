"""Задача отправки письма (M3-CRM-08, W18A-P1): письмо уходит не в пути запроса.

Повторы — `RetryStrategy` Procrastinate; сервис сам считает попытки по строке журнала и на
последней попытке не бросает (строка `failed` с причиной, тело стёрто). Задача одной строки —
одна в очереди (`queueing_lock`) и не идёт параллельно с другой такой же (`lock`): повторная
постановка (сборщик, включение «Почты») второго письма не даёт.
"""

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued

from app.container import get_container
from app.services.mail import MAX_ATTEMPTS
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=MAX_ATTEMPTS, wait=30)


@queue.task(name="send_email", queue="notify", retry=RETRY)
async def send_email(email_log_id: int) -> bool:
    return await get_container().mail_service.deliver(email_log_id)


async def enqueue_email(email_log_id: int) -> int | None:
    lock = f"email_log:{email_log_id}"
    try:
        job_id: int = await send_email.configure(lock=lock, queueing_lock=lock).defer_async(
            email_log_id=email_log_id
        )
    except AlreadyEnqueued:
        return None
    return job_id


@queue.periodic(cron="*/2 * * * *", periodic_id="email_queue_sweep")
@queue.task(name="email_queue_sweep", queue="notify", queueing_lock="email_queue_sweep")
async def email_queue_sweep(timestamp: int) -> int:
    """Раз в 2 минуты: письма `queued`, постановка которых потерялась (сбой после коммита)."""
    return await get_container().mail_service.sweep()
