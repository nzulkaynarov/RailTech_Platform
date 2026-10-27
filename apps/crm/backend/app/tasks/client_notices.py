"""Задачи после приёма запроса с сайта (D1-9): подтверждение клиенту, сообщение менеджерам, проверка
срока ответа.

* `deliver_client_notice` — отправить подтверждение (Telegram, иначе письмо); временный сбой
  повторяет Procrastinate;
* `notify_web_lead` — личное сообщение менеджерам с включёнными уведомлениями о лидах (без повторов:
  уже
  доставленным второе сообщение вредно);
* `web_lead_sla_check` — в срок `first_response_due_at`: никто не взял — один раз напомнить.
"""

from datetime import UTC, datetime

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued

from app.container import get_container
from app.services import web_lead_sla
from app.services.lead_intake import WebLeadFollowUp
from app.services.staff_notifier import StaffNotifier
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)


@queue.task(name="deliver_client_notice", queue="notify", retry=RETRY)
async def deliver_client_notice(notice_id: int) -> str:
    outcome: str = await get_container().client_notice_service.deliver(notice_id)
    return outcome


@queue.task(name="notify_web_lead", queue="notify")
async def notify_web_lead(lead_id: int) -> int:
    c = get_container()
    cfg = await c.settings_service.get()
    notifier = StaffNotifier(c.session_factory, await c.telegram_bot())
    return await notifier.web_lead(
        lead_id, cfg.company.crm_base_url, cfg.web_form.first_response_sla_minutes
    )


@queue.task(name="web_lead_sla_check", queue="timers")
async def web_lead_sla_check(lead_id: int) -> bool:
    c = get_container()
    if not await web_lead_sla.mark_overdue(c.session_factory, lead_id, datetime.now(UTC)):
        return False
    cfg = await c.settings_service.get()
    notifier = StaffNotifier(c.session_factory, await c.telegram_bot())
    await notifier.web_lead(
        lead_id, cfg.company.crm_base_url, cfg.web_form.first_response_sla_minutes, overdue=True
    )
    return True


async def enqueue_web_lead(follow_up: WebLeadFollowUp) -> None:
    """После коммита запроса с сайта: подтверждение клиенту, сообщение менеджерам, таймер срока."""
    if follow_up.notice_id is not None:
        await deliver_client_notice.defer_async(notice_id=follow_up.notice_id)
    await notify_web_lead.defer_async(lead_id=follow_up.lead_id)
    if follow_up.sla_due_at is not None:
        try:
            await web_lead_sla_check.configure(
                queueing_lock=f"web-sla-{follow_up.lead_id}", schedule_at=follow_up.sla_due_at
            ).defer_async(lead_id=follow_up.lead_id)
        except AlreadyEnqueued:
            return


__all__ = ["enqueue_web_lead"]
