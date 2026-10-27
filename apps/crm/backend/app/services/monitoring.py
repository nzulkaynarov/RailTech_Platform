"""Монитор эксплуатации (SPEC §13): алерты ⚠️ и ежедневный отчёт.

Алерт — в личку админам, подписанным на системные уведомления (Q-010, аудит 2026-10-12 §3 п. 8);
никому не доставлено → в канал команды (запасной путь). Итоги дня — в канал, стоимость
моделей — только админам в личку.

Алерт уходит на переходе «норма → проблема», повторяется не чаще 6 ч и снимается
постом «✅ в норме». Состояние — `system_alerts` (переживает рестарты воркера).
Решение и состояние сохраняются в транзакции, отправка — после коммита: недоступный
Telegram не откатывает состояние и не роняет монитор. Не доставленный алерт остаётся
без `sent_at` и уходит со следующим проходом.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.alerts import (
    RETIRED_KEYS,
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
from app.services import channel_texts as tx
from app.services.channel_card import duration
from app.services.settings import SettingsService
from app.services.staff_notifier import SEND_TIMEOUT_S, StaffNotifier

logger = structlog.get_logger(__name__)
FAILED_WINDOW = timedelta(hours=1)
Probe = Callable[[], Awaitable[bool]]
# Проверка моделей у провайдеров: алиас → проблема (кредиты, ключ) или None.
ModelProbe = Callable[[], Awaitable[dict[str, str | None]]]


@dataclass(frozen=True, slots=True)
class _Outgoing:
    key: str
    text: str
    decision: Decision


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
        """Один проход монитора; возвращает доставленные сообщения."""
        cfg = await self._settings.get()
        litellm_ok = await self._probe()
        models = (
            await self._model_probe()
            if self._model_probe is not None and litellm_ok and model_probe_due(now)
            else None
        )
        outgoing = await self._decide(
            now, litellm_ok, models, cfg.budget.daily_usd, cfg.business_hours.timezone
        )
        sent: list[str] = []
        delivered: list[str] = []
        for item in outgoing:
            if await self._alert(cfg.notifications.channel_id, item.text, item.key):
                sent.append(item.text)
                if item.decision is not Decision.RESOLVE:
                    delivered.append(item.key)
        if delivered:
            await self._mark_sent(delivered, now)
        return sent

    async def _decide(
        self,
        now: datetime,
        litellm_ok: bool,
        models: dict[str, str | None] | None,
        daily_usd: float,
        timezone: str,
    ) -> list[_Outgoing]:
        """Состояние алертов — в транзакции; что отправить — после коммита."""
        outgoing: list[_Outgoing] = []
        async with self._sessions() as session, session.begin():
            states = await repo.alert_states(session)
            if models is not None:
                models = {**_orphan_models(states), **models}
            known = {
                key.split(":", 1)[1]
                for key, row in states.items()
                if key.startswith("failed_task:") and row.active
            }
            failed = await repo.failed_tasks(session, now - FAILED_WINDOW)
            snapshot = HealthSnapshot(
                failed_tasks=failed,
                queue_size=await repo.queue_size(session),
                litellm_ok=litellm_ok,
                spent_usd=await repo.spent_since(session, day_start(now, timezone)),
                daily_budget_usd=daily_usd,
                models=models,
                recovered_tasks=await repo.recovered_tasks(session, set(failed) | known),
            )
            for item in checks(snapshot, known, tx.task):
                row = states.get(item.key)
                state = AlertState(row.first_seen_at, row.sent_at) if row and row.active else None
                decision = decide(item, state, now)
                if decision is not Decision.NONE:
                    outgoing.append(_Outgoing(item.key, alert_text(item, decision), decision))
                _apply(session, row, item, now)
            for key in RETIRED_KEYS:  # прежние алерты ушли в центр внешних сервисов — закрыть молча
                old = states.get(key)
                if old is not None and old.active:
                    old.active, old.resolved_at, old.first_seen_at, old.sent_at = (
                        False,
                        now,
                        None,
                        None,
                    )
                    old.updated_at = now
        return outgoing

    async def _mark_sent(self, keys: list[str], now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            rows = await session.scalars(select(SystemAlert).where(SystemAlert.key.in_(keys)))
            for row in rows:
                if row.active:
                    row.sent_at = now

    async def daily_report(self, now: datetime) -> str | None:
        """Итоги дня в канал (General-пост); стоимость моделей — админам в личку."""
        cfg = await self._settings.get()
        since = day_start(now, cfg.business_hours.timezone)
        async with self._sessions() as session:
            f = await repo.daily_figures(session, since)
        day = f"{since.astimezone(ZoneInfo(cfg.business_hours.timezone)):%d.%m}"
        dashboard = (await self._settings.links()).dashboard()
        text = report_text(f, day, dashboard)
        cost = f"${f.cost_usd:.2f}"
        if cfg.budget.daily_usd > 0:
            cost = tx.REPORT_COST_LIMIT.format(spent=cost, limit=f"${cfg.budget.daily_usd:.2f}")
        await self._staff.alert_admins(tx.REPORT_COST.format(day=day, cost=cost), "daily_cost")
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
        try:
            await self._bot.send_message(
                channel, text, parse_mode="HTML", request_timeout=SEND_TIMEOUT_S
            )
        except TelegramAPIError as exc:
            logger.warning("monitor_post_failed", alert=key, error=type(exc).__name__)
            return False
        logger.info("monitor_posted", alert=key)
        return True


def alert_text(item: Check, decision: Decision) -> str:
    """Текст алерта (HTML-безопасный) с «что делать» для проблем."""
    text = escape(message(item, decision), quote=False)
    if decision is not Decision.RESOLVE and item.hint:
        text += "\n" + tx.ALERT_HINT.format(hint=escape(item.hint, quote=False))
    return text


def report_text(f: repo.DailyFigures, day: str, dashboard_url: str) -> str:
    lines = [
        tx.REPORT_TITLE.format(day=day),
        tx.REPORT_LEADS.format(n=f.leads),
        tx.REPORT_ESCALATIONS.format(n=f.escalations, open=f.open_escalations),
        tx.REPORT_SLA.format(n=f.sla_overdue),
    ]
    if f.take_median_s is not None:
        median = duration(timedelta(seconds=f.take_median_s))
        lines.append(tx.REPORT_TAKE_MEDIAN.format(waited=median))
    if f.taken_by:
        items = ", ".join(f"{escape(name)} — {n}" for name, n in f.taken_by)
        lines.append(tx.REPORT_TAKEN_BY.format(items=items))
    lines.append(tx.REPORT_GAPS.format(n=f.open_gaps))
    if f.top_gaps:
        lines.append(
            tx.REPORT_TOP_GAPS.format(items="; ".join(f"«{escape(q)}»" for q in f.top_gaps))
        )
    lines.append(tx.REPORT_DASHBOARD.format(url=escape(dashboard_url, quote=True)))
    return "\n".join(lines)


def _apply(session: AsyncSession, row: SystemAlert | None, item: Check, now: datetime) -> None:
    """Состояние проверки по факту, независимо от доставки; `sent_at` ставит `_mark_sent`.

    Модели: строка есть и у исправной модели, `updated_at` — время последней пробы
    («проверено N назад» в «Состоянии системы»)."""
    probed = item.key.startswith("model:")
    if not item.active:
        if row is None and probed:
            session.add(SystemAlert(key=item.key, active=False, detail=None, updated_at=now))
        elif row is not None and row.active:
            row.active, row.resolved_at, row.first_seen_at, row.sent_at = False, now, None, None
            row.updated_at = now
        elif row is not None and probed:
            row.updated_at = now
        return
    if row is None:
        row = SystemAlert(key=item.key, active=False)
        session.add(row)
    if not row.active:
        row.active, row.first_seen_at, row.sent_at, row.resolved_at = True, now, None, None
    row.detail, row.updated_at = item.detail, now


def _orphan_models(states: dict[str, SystemAlert]) -> dict[str, str | None]:
    """Алерты моделей, которые монитор больше не проверяет, закрываются с очередной пробой:
    иначе снятая с проб модель навсегда висит «Сбоем» в «Состоянии системы» и чек-листе."""
    return {
        key.split(":", 1)[1]: None
        for key, row in states.items()
        if key.startswith("model:") and row.active
    }
