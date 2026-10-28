"""Задачи уведомлений: канал команды (SPEC §8.2) и личные сообщения менеджеру (Q-010)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import select

from app.bot import commands
from app.container import Container, get_container
from app.domain.business_hours import add_business_minutes
from app.domain.escalation import reset_sla
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import events
from app.services.channel_card import needs_sla
from app.services.client_bot import ClientBotService
from app.services.notifications import NotificationService
from app.services.staff_notifier import StaffNotifier
from app.tasks.queue import queue

RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)


async def build_notifications(c: Container) -> NotificationService:
    return NotificationService(c.session_factory, c.settings_service, await c.telegram_bot())


@queue.task(name="sync_escalation_post", queue="notify", retry=RETRY)
async def sync_escalation_post(escalation_id: int) -> bool:
    result = await (await build_notifications(get_container())).publish(escalation_id)
    if result.raised_to_hot:
        await _schedule_sla(escalation_id)  # срок сбросил services/escalation (reset_sla)
    return result.ok


@queue.task(name="escalation_sla_check", queue="notify", retry=RETRY)
async def escalation_sla_check(escalation_id: int) -> bool:
    c = get_container()
    marked = await (await build_notifications(c)).mark_sla_overdue(escalation_id)
    if marked:
        cfg = await c.settings_service.get()
        due = add_business_minutes(
            datetime.now(UTC), cfg.escalation.reminder_minutes, cfg.business_hours.domain()
        )
        await _defer(escalation_reminder, f"reminder-{escalation_id}", due, escalation_id)
    return marked


@queue.task(name="escalation_reminder", queue="notify", retry=RETRY)
async def escalation_reminder(escalation_id: int) -> bool:
    return await (await build_notifications(get_container())).remind(escalation_id)


@queue.periodic(cron="5 4 * * 1-5", periodic_id="escalation_digest")  # 09:05 Ташкент
@queue.task(name="escalation_digest", queue="notify", queueing_lock="escalation_digest")
async def escalation_digest(timestamp: int) -> int:
    return await (await build_notifications(get_container())).digest()


@queue.periodic(cron="*/5 * * * *", periodic_id="snooze_expiry")
@queue.task(name="snooze_expiry", queue="timers", queueing_lock="snooze_expiry")
async def snooze_expiry(timestamp: int) -> int:
    """Снуз истёк → эскалация снова открыта, пост обновлён."""
    c = get_container()
    now = datetime.fromtimestamp(timestamp, UTC)
    reopened: list[int] = []
    async with c.session_factory() as session, session.begin():
        # Порядок блокировок как у «Забрать»/«Отложить» (services/leads.py): сначала лид,
        # потом эскалация. Обратный порядок (эскалация → лид) давал взаимную блокировку
        # с ручными действиями менеджера. Занятые строки пропускаем — следующий прогон.
        due = select(Escalation.lead_id).where(
            Escalation.status == "snoozed", Escalation.snoozed_until <= now
        )
        leads = {
            lead.id: lead
            for lead in (
                await session.scalars(
                    select(Lead)
                    .where(Lead.id.in_(due))
                    .order_by(Lead.id)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        }
        rows = (
            await session.scalars(
                select(Escalation)
                .where(
                    Escalation.status == "snoozed",
                    Escalation.snoozed_until <= now,
                    Escalation.lead_id.in_(list(leads)),
                )
                .order_by(Escalation.id)
                .with_for_update(skip_locked=True)
            )
        ).all()
        cfg = await c.settings_service.get()
        for row in rows:
            row.status, row.snoozed_until = "open", None
            if needs_sla(row.priority):  # после «Отложить» срок реакции отсчитывается заново
                timer = reset_sla(now, cfg.escalation.sla_minutes, cfg.business_hours.domain())
                row.sla_due_at, row.sla_notified_at = timer.sla_due_at, timer.sla_notified_at
            leads[row.lead_id].snoozed_until = None
            await events.publish(
                session, "escalation.updated", lead_id=row.lead_id, escalation_id=row.id
            )
            reopened.append(row.id)
    notifications = await build_notifications(c)
    for escalation_id in reopened:
        await enqueue_escalation(escalation_id, new=False)
        await notifications.reopened(escalation_id)
        await _schedule_sla(escalation_id)
    return len(reopened)


@queue.task(name="lead_handed_over", queue="notify", retry=RETRY)
async def lead_handed_over(lead_id: int, user_id: int) -> bool:
    """«Передать коллеге»: карточка в канале — на нового ответственного, ему — личное сообщение."""
    c = get_container()
    bot = await c.telegram_bot()
    escalation_id = await NotificationService(
        c.session_factory, c.settings_service, bot
    ).handed_over(lead_id, user_id)
    if escalation_id is not None:
        await enqueue_escalation(escalation_id, new=False)
    notifier = StaffNotifier(c.session_factory, bot)
    return await notifier.handed_over(lead_id, user_id, await c.settings_service.links())


async def enqueue_handover(lead_id: int, user_id: int) -> None:
    await lead_handed_over.defer_async(lead_id=lead_id, user_id=user_id)


@queue.task(name="notify_lead_message", queue="notify")
async def notify_lead_message(lead_id: int) -> bool:
    """Новое сообщение лида в работе у менеджера → личное сообщение ему (без повторов)."""
    c = get_container()
    cfg = await c.settings_service.get()
    window = timedelta(minutes=cfg.notifications.manager_dm_throttle_minutes)
    notifier = StaffNotifier(c.session_factory, await c.telegram_bot())
    links = await c.settings_service.links()
    return await notifier.lead_message(lead_id, datetime.now(UTC), window, links)


async def enqueue_lead_message(lead_id: int) -> None:
    """Пачка сообщений подряд — одна задача в очереди (queueing_lock)."""
    try:
        await notify_lead_message.configure(queueing_lock=f"lead-dm-{lead_id}").defer_async(
            lead_id=lead_id
        )
    except AlreadyEnqueued:
        return


@queue.task(name="refresh_chat_menu", queue="notify")
async def refresh_chat_menu(tg_user_id: int) -> bool:
    """Меню чата лида по статусу сразу после действия в CRM (Забрать, Вернуть боту, клиент)."""
    c = get_container()
    bot = await c.telegram_bot()
    if bot is None or c.settings.telegram_dry_run:
        return False
    client_bot = ClientBotService(c.session_factory, c.settings_service)
    return await commands.refresh_chat_menu(bot, client_bot, c.settings_service, tg_user_id)


async def enqueue_chat_menus(tg_user_ids: Sequence[int]) -> None:
    """После коммита: по задаче на чат; ещё не начатая задача того же чата — одна (lock)."""
    for tg_user_id in tg_user_ids:
        try:
            await refresh_chat_menu.configure(queueing_lock=f"menu-{tg_user_id}").defer_async(
                tg_user_id=tg_user_id
            )
        except AlreadyEnqueued:
            continue


async def enqueue_escalation(escalation_id: int, *, new: bool = True) -> None:
    """Обновить пост сейчас; для новой эскалации — проверка SLA в срок `sla_due_at`."""
    await sync_escalation_post.configure(lock=f"escalation-{escalation_id}").defer_async(
        escalation_id=escalation_id
    )
    if new:
        await _schedule_sla(escalation_id)


async def _schedule_sla(escalation_id: int) -> None:
    """Проверка срока реакции в `sla_due_at` — только для тёплых и горячих (info — сигнал)."""
    c = get_container()
    async with c.session_factory() as session:
        row = (
            await session.execute(
                select(Escalation.sla_due_at, Escalation.priority).where(
                    Escalation.id == escalation_id
                )
            )
        ).first()
    if row is None or row.sla_due_at is None or not needs_sla(row.priority):
        return
    # Ключ со сроком: перезапуск срока ставит новую проверку, старая отработает вхолостую.
    lock = f"sla-{escalation_id}-{int(row.sla_due_at.timestamp())}"
    await _defer(escalation_sla_check, lock, row.sla_due_at, escalation_id)


async def _defer(task: object, lock: str, at: datetime, escalation_id: int) -> None:
    try:
        await task.configure(queueing_lock=lock, schedule_at=at).defer_async(  # type: ignore[attr-defined]
            escalation_id=escalation_id
        )
    except AlreadyEnqueued:
        return
