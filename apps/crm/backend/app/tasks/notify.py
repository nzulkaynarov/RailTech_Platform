"""Задачи канала команды (SPEC §8.2): пост/редактирование, SLA, напоминание, сводка, снуз."""

from datetime import UTC, datetime

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import select

from app.container import Container, get_container
from app.domain.business_hours import add_business_minutes
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import events
from app.services.notifications import NotificationService
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)


def build_notifications(c: Container) -> NotificationService:
    return NotificationService(c.session_factory, c.settings_service, c.telegram_bot)


@queue.task(name="sync_escalation_post", queue="notify", retry=RETRY)
async def sync_escalation_post(escalation_id: int) -> bool:
    return await build_notifications(get_container()).sync(escalation_id)


@queue.task(name="escalation_sla_check", queue="notify", retry=RETRY)
async def escalation_sla_check(escalation_id: int) -> bool:
    c = get_container()
    marked = await build_notifications(c).mark_sla_overdue(escalation_id)
    if marked:
        cfg = await c.settings_service.get()
        due = add_business_minutes(
            datetime.now(UTC), cfg.escalation.reminder_minutes, cfg.business_hours.domain()
        )
        await _defer(escalation_reminder, f"reminder-{escalation_id}", due, escalation_id)
    return marked


@queue.task(name="escalation_reminder", queue="notify", retry=RETRY)
async def escalation_reminder(escalation_id: int) -> bool:
    return await build_notifications(get_container()).remind(escalation_id)


@queue.periodic(cron="5 4 * * 1-5", periodic_id="escalation_digest")  # 09:05 Ташкент
@queue.task(name="escalation_digest", queue="notify", queueing_lock="escalation_digest")
async def escalation_digest(timestamp: int) -> int:
    return await build_notifications(get_container()).digest()


@queue.periodic(cron="*/5 * * * *", periodic_id="snooze_expiry")
@queue.task(name="snooze_expiry", queue="timers", queueing_lock="snooze_expiry")
async def snooze_expiry(timestamp: int) -> int:
    """Снуз истёк → эскалация снова открыта, пост обновлён."""
    c = get_container()
    now = datetime.fromtimestamp(timestamp, UTC)
    reopened: list[int] = []
    async with c.session_factory() as session, session.begin():
        rows = (
            await session.scalars(
                select(Escalation)
                .where(Escalation.status == "snoozed", Escalation.snoozed_until <= now)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            row.status, row.snoozed_until = "open", None
            lead = await session.get(Lead, row.lead_id, with_for_update=True)
            if lead is not None:
                lead.snoozed_until = None
            await events.publish(
                session, "escalation.updated", lead_id=row.lead_id, escalation_id=row.id
            )
            reopened.append(row.id)
    for escalation_id in reopened:
        await enqueue_escalation(escalation_id, new=False)
    return len(reopened)


async def enqueue_escalation(escalation_id: int, *, new: bool = True) -> None:
    """Обновить пост сейчас; для новой эскалации — проверка SLA в срок `sla_due_at`."""
    await sync_escalation_post.configure(lock=f"escalation-{escalation_id}").defer_async(
        escalation_id=escalation_id
    )
    if not new:
        return
    c = get_container()
    async with c.session_factory() as session:
        due = await session.scalar(
            select(Escalation.sla_due_at).where(Escalation.id == escalation_id)
        )
    if due is not None:
        await _defer(escalation_sla_check, f"sla-{escalation_id}", due, escalation_id)


async def _defer(task: object, lock: str, at: datetime, escalation_id: int) -> None:
    try:
        await task.configure(queueing_lock=lock, schedule_at=at).defer_async(  # type: ignore[attr-defined]
            escalation_id=escalation_id
        )
    except AlreadyEnqueued:
        return
