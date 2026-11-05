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


@shared_task(
    name="portal.send_notice_email",
    time_limit=120,
    soft_time_limit=100,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_notice_email(notice_id: int) -> dict:
    """Письмо по уведомлению кабинета (NOTIFY-2), если оно ещё нужно. Повтор задачи второго письма не шлёт: строка
    блокируется, отправленное и отменённое пропускаются (`portal.services.notices.deliver_email`)."""
    from portal.services.notices import deliver_email

    return {"notice_id": notice_id, "result": deliver_email(notice_id)}


@shared_task(name="portal.send_due_notice_emails", time_limit=300, soft_time_limit=270)
def send_due_notice_emails() -> dict:
    """Сборщик раз в минуту (Beat): отложенные письма (ответ менеджера — через 10 минут, если не прочитано и контакт не
    заходил) и письма, которые не удалось поставить в очередь после коммита."""
    from portal.services.notices import send_due_emails

    return send_due_emails()
