"""Celery-задачи портала (FIX-15)."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="portal.send_magic_link",
    time_limit=120,
    soft_time_limit=100,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_magic_link(contact_id: int) -> dict:
    """Выпускает ссылку входа и отправляет письмо вне потока запроса.

    Аргумент — только id контакта: сырой токен рождается и живёт внутри задачи, в брокер (Redis) и в журнал
    Celery он не попадает. Сбой SMTP — `EmailDeliveryError` — повторяется с задержкой (`autoretry_for`).
    """
    from portal.services.magic_link import deliver_login_link

    sent = deliver_login_link(contact_id)
    return {"contact_id": contact_id, "sent": sent}
