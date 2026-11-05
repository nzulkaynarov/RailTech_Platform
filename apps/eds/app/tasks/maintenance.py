"""Служебные задачи сервиса: уборка использованных `jti` SSO-токенов и просроченных ключей идемпотентности, напоминания
о сроках поручений по входящим (P8b)."""

from app import clock
from app.container import get_container
from app.services import idempotency, instructions, signing_reminders
from app.services.sso import purge_expired_jti
from app.tasks.queue import queue


@queue.periodic(cron="*/10 * * * *", periodic_id="sso_jti_cleanup")
@queue.task(name="sso_jti_cleanup", queue="maintenance", queueing_lock="sso_jti_cleanup")
async def sso_jti_cleanup(timestamp: int) -> int:
    """Раз в 10 минут: удалить `jti`, которым больше 10 минут."""
    async with get_container().session_factory() as session, session.begin():
        return await purge_expired_jti(session)


@queue.periodic(cron="17 * * * *", periodic_id="idempotency_cleanup")
@queue.task(name="idempotency_cleanup", queue="maintenance", queueing_lock="idempotency_cleanup")
async def idempotency_cleanup(timestamp: int) -> int:
    """Раз в час: удалить ключи `Idempotency-Key` старше 24 часов."""
    async with get_container().session_factory() as session, session.begin():
        return await idempotency.purge_expired(session)


@queue.periodic(cron="*/30 * * * *", periodic_id="instruction_reminders")
@queue.task(name="instruction_reminders", queue="maintenance", queueing_lock="instruction_reminders")
async def instruction_reminders(timestamp: int) -> int:
    """Раз в 30 минут: напоминания о сроках поручений и «Просрочено» (с 9:00 по Ташкенту; одно на срок)."""
    container = get_container()
    async with container.session_factory() as session, session.begin():
        return await instructions.send_reminders(session, container.bus, now=clock.now())


@queue.periodic(cron="*/30 * * * *", periodic_id="signing_expiry_reminders")
@queue.task(name="signing_expiry_reminders", queue="maintenance", queueing_lock="signing_expiry_reminders")
async def signing_expiry_reminders(timestamp: int) -> int:
    """Раз в 30 минут: напомнить держателям `signing.manage` о полномочиях подписи, которые кончаются через 14 дней
    (с 9:00 по Ташкенту; одно напоминание на полномочие и дату окончания)."""
    container = get_container()
    async with container.session_factory() as session, session.begin():
        return await signing_reminders.send_expiry_reminders(session, container.bus, now=clock.now())
