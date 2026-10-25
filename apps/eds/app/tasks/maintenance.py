"""Служебные задачи сервиса: уборка использованных `jti` SSO-токенов."""

from app.container import get_container
from app.services.sso import purge_expired_jti
from app.tasks.queue import queue


@queue.periodic(cron="*/10 * * * *", periodic_id="sso_jti_cleanup")
@queue.task(name="sso_jti_cleanup", queue="maintenance", queueing_lock="sso_jti_cleanup")
async def sso_jti_cleanup(timestamp: int) -> int:
    """Раз в 10 минут: удалить `jti`, которым больше 10 минут."""
    async with get_container().session_factory() as session, session.begin():
        return await purge_expired_jti(session)
