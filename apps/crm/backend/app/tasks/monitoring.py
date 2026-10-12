"""Монитор эксплуатации (SPEC §13): алерты раз в минуту и итоги дня в канал."""

from datetime import UTC, datetime

import httpx

from app.container import Container, get_container
from app.integrations import litellm
from app.services import models_status
from app.services.monitoring import ModelProbe, MonitorService
from app.tasks.queue import queue


async def build_monitor(c: Container) -> MonitorService:
    async def litellm_ok() -> bool:
        try:
            async with httpx.AsyncClient(timeout=c.settings.ready_check_timeout_s) as http:
                await litellm.ping(http, c.settings.litellm_base_url)
        except httpx.HTTPError:
            return False
        return True

    return MonitorService(
        c.session_factory, c.settings_service, await c.telegram_bot(), litellm_ok, _model_probe(c)
    )


# По одной модели на провайдера: кредиты/ключ — общие для всех моделей провайдера.
PROBED_ALIASES = ("dialog-model", "fallback-model")


def _model_probe(c: Container) -> ModelProbe:
    """Запрос в 1 токен к каждой модели без запасного перехода LiteLLM (`disable_fallbacks`):
    иначе сбой Claude маскируется ответом Gemini. Ловим «нет кредитов/квоты» и отклонённый ключ.
    Каждый вызов — в учёте расходов (`probe`) и под лимитами провайдеров (BudgetGuard).
    """

    async def probe() -> dict[str, str | None]:
        return await models_status.monitor_probe(
            c.llm, PROBED_ALIASES, c.usage_recorder, c.budget_guard
        )

    return probe


@queue.periodic(cron="* * * * *", periodic_id="system_monitor")
@queue.task(name="system_monitor", queue="timers", queueing_lock="system_monitor")
async def system_monitor(timestamp: int) -> int:
    monitor = await build_monitor(get_container())
    sent = await monitor.check(datetime.fromtimestamp(timestamp, UTC))
    return len(sent)


@queue.periodic(cron="5 13 * * 1-5", periodic_id="daily_report")  # 18:05 Ташкент
@queue.task(name="daily_report", queue="notify", queueing_lock="daily_report")
async def daily_report(timestamp: int) -> bool:
    monitor = await build_monitor(get_container())
    text = await monitor.daily_report(datetime.fromtimestamp(timestamp, UTC))
    return text is not None
