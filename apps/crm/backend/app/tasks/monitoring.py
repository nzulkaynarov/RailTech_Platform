"""Монитор эксплуатации (SPEC §13): алерты раз в минуту и итоги дня в канал."""

from datetime import UTC, datetime

import httpx

from app.container import Container, get_container
from app.integrations import litellm
from app.services.monitoring import MonitorService
from app.tasks.queue import queue


def build_monitor(c: Container) -> MonitorService:
    async def litellm_ok() -> bool:
        try:
            async with httpx.AsyncClient(timeout=c.settings.ready_check_timeout_s) as http:
                await litellm.ping(http, c.settings.litellm_base_url)
        except httpx.HTTPError:
            return False
        return True

    return MonitorService(c.session_factory, c.settings_service, c.telegram_bot, litellm_ok)


@queue.periodic(cron="* * * * *", periodic_id="system_monitor")
@queue.task(name="system_monitor", queue="timers", queueing_lock="system_monitor")
async def system_monitor(timestamp: int) -> int:
    sent = await build_monitor(get_container()).check(datetime.fromtimestamp(timestamp, UTC))
    return len(sent)


@queue.periodic(cron="5 13 * * 1-5", periodic_id="daily_report")  # 18:05 Ташкент
@queue.task(name="daily_report", queue="notify", queueing_lock="daily_report")
async def daily_report(timestamp: int) -> bool:
    text = await build_monitor(get_container()).daily_report(datetime.fromtimestamp(timestamp, UTC))
    return text is not None
