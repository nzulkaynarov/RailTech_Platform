"""Служебные задачи сервиса: уборка использованных `jti` SSO-токенов и просроченных ключей идемпотентности."""

from app.container import get_container
from app.services import idempotency
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
