"""Монитор эксплуатации (SPEC §13): алерты ⚠️ и ежедневный отчёт.

Алерт — в личку админам, подписанным на системные уведомления (Q-010, аудит 2026-10-12 §3 п. 8);
никому не доставлено → в канал команды (запасной путь). Итоги дня — в канал.

Алерт уходит на переходе «норма → проблема», повторяется не чаще 6 ч и снимается
постом «✅ в норме». Состояние — `system_alerts` (переживает рестарты воркера).
Отправка внутри транзакции: упал Telegram → состояние не изменилось, повтор через минуту.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import structlog
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.alerts import (
    AlertState,
    Check,
    Decision,
    HealthSnapshot,
    checks,
    decide,
    message,
    model_probe_due,
)
from app.domain.budget import day_start
from app.models.system import SystemAlert
from app.repositories import monitoring as repo
from app.services.settings import SettingsService
from app.services.staff_notifier import StaffNotifier

logger = structlog.get_logger(__name__)
FAILED_WINDOW = timedelta(hours=1)
Probe = Callable[[], Awaitable[bool]]
# Проверка моделей у провайдеров: алиас → проблема (кредиты, ключ) или None.
ModelProbe = Callable[[], Awaitable[dict[str, str | None]]]


class MonitorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        bot: Bot | None,
        litellm_probe: Probe,
        model_probe: ModelProbe | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._bot = bot
        self._probe = litellm_probe
        self._model_probe = model_probe
        self._staff = StaffNotifier(sessions, bot)

    async def check(self, now: datetime) -> list[str]:
        """Один проход монитора; возвращает отправленные в канал сообщения."""
        cfg = await self._settings.get()
        channel = cfg.notifications.channel_id
        litellm_ok = await self._probe()
        models = (
            await self._model_probe()
            if self._model_probe is not None and litellm_ok and model_probe_due(now)
            else None
        )
        sent: list[str] = []
        async with self._sessions() as session, session.begin():
            states = await repo.alert_states(session)
            if models is not None:
                models = {**_orphan_models(states), **models}
            snapshot = HealthSnapshot(
                failed_tasks=await repo.failed_tasks(session, now - FAILED_WINDOW),
                queue_size=await repo.queue_size(session),
                litellm_ok=litellm_ok,
                spent_usd=await repo.spent_since(
                    session, day_start(now, cfg.business_hours.timezone)
                ),
                daily_budget_usd=cfg.budget.daily_usd,
                models=models,
            )
            known = {
                key.split(":", 1)[1]
                for key, row in states.items()
                if key.startswith("failed_task:") and row.active
            }
            for item in checks(snapshot, known):
                row = states.get(item.key)
                state = AlertState(row.first_seen_at, row.sent_at) if row and row.active else None
                decision = decide(item, state, now)
                delivered = False
                if decision is not Decision.NONE:
                    text = message(item, decision)
                    delivered = await self._alert(channel, text, item.key)
                    if delivered:
                        sent.append(text)
                _apply(session, row, item, decision, delivered, now)
        return sent

    async def daily_report(self, now: datetime) -> str | None:
        """Итоги дня в канал (General-пост): лиды, эскалации, пробелы KB, стоимость."""
        cfg = await self._settings.get()
        since = day_start(now, cfg.business_hours.timezone)
        async with self._sessions() as session:
            f = await repo.daily_figures(session, since)
        budget = f"${f.cost_usd:.2f}"
        if cfg.budget.daily_usd > 0:
            budget += f" из ${cfg.budget.daily_usd:.2f}"
        text = "\n".join(
            [
                f"📊 Итоги дня {since:%d.%m}",
                f"• новых лидов: {f.leads}",
                f"• эскалаций: {f.escalations} (открыто сейчас: {f.open_escalations})",
                f"• открытых пробелов KB: {f.open_gaps}",
                f"• стоимость моделей: {budget}",
            ]
        )
        channel = cfg.notifications.channel_id
        return text if await self._send(channel, text, "daily_report") else None

    async def _alert(self, channel: int | None, text: str, key: str) -> bool:
        """Сначала личные сообщения админам; не доставлено никому — канал команды."""
        if await self._staff.alert_admins(text, key) > 0:
            return True
        return await self._send(channel, text, key)

    async def _send(self, channel: int | None, text: str, key: str) -> bool:
        if self._bot is None or channel is None:
            logger.info("monitor_channel_not_configured", alert=key)
            return False
        await self._bot.send_message(channel, text)
        logger.info("monitor_posted", alert=key)
        return True


def _apply(
    session: AsyncSession,
    row: SystemAlert | None,
    item: Check,
    decision: Decision,
    delivered: bool,
    now: datetime,
) -> None:
    if not item.active:
        if row is not None and row.active and (decision is Decision.NONE or delivered):
            row.active, row.resolved_at, row.first_seen_at, row.sent_at = False, now, None, None
            row.updated_at = now
        return
    if row is None:
        row = SystemAlert(key=item.key, active=False)
        session.add(row)
    if not row.active:
        row.active, row.first_seen_at, row.sent_at, row.resolved_at = True, now, None, None
    row.detail, row.updated_at = item.detail, now
    if delivered:
        row.sent_at = now


def _orphan_models(states: dict[str, SystemAlert]) -> dict[str, str | None]:
    """Алерты моделей, которые монитор больше не проверяет, закрываются с очередной пробой:
    иначе снятая с проб модель навсегда висит «Сбоем» в «Состоянии системы» и чек-листе."""
    return {
        key.split(":", 1)[1]: None
        for key, row in states.items()
        if key.startswith("model:") and row.active
    }
