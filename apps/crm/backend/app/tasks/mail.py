"""Задача отправки письма сотруднику (M3-CRM-08): письмо уходит не в пути запроса.

Повторы — `RetryStrategy` Procrastinate; сервис сам считает попытки по строке журнала и на
последней попытке не бросает (строка `failed` с причиной, тело стёрто).
"""

from procrastinate import RetryStrategy

from app.container import get_container
from app.services.mail import MAX_ATTEMPTS
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=MAX_ATTEMPTS, wait=30)


@queue.task(name="send_email", queue="notify", retry=RETRY)
async def send_email(email_log_id: int) -> bool:
    return await get_container().mail_service.deliver(email_log_id)


async def enqueue_email(email_log_id: int) -> int:
    job_id: int = await send_email.defer_async(email_log_id=email_log_id)
    return job_id
