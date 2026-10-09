"""Периодическое обновление агрегатов дашборда (каждые 10 минут)."""

from app.container import get_container
from app.services import dashboard
from app.tasks.queue import queue


@queue.periodic(cron="*/10 * * * *", periodic_id="refresh_dashboard")
@queue.task(name="refresh_dashboard", queue="timers", queueing_lock="refresh_dashboard")
async def refresh_dashboard(timestamp: int) -> None:
    c = get_container()
    async with c.session_factory() as session, session.begin():
        await dashboard.refresh(session)
