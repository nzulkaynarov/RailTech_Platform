"""Повторная публикация имени бота (`crm.bot.changed`) при старте воркера.

Имя бота знает только CRM: процесс бота получает его у Telegram (`getMe`) и пишет в
`bot_runtime`; событие уходит в той же транзакции, когда имя новое (`BotStateService.report`).
Если ERP в тот момент не было на шине (новая выкладка, сбой доставки), воркер CRM при каждом
старте публикует последнее известное имя заново — по образцу `company_profile_publish.py`.
Бот ни разу не запускался — публиковать нечего. Сбой не пробрасывается: старт воркера от шины
не зависит.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import snapshots
from app.models.system import BotRuntimeState

logger = structlog.get_logger(__name__)


async def republish_bot(sessions: async_sessionmaker[AsyncSession]) -> str | None:
    """Опубликовать последнее известное имя бота; вернуть его (`None` — бот ещё не запускался)."""
    async with sessions() as session, session.begin():
        row = (
            await session.execute(
                select(
                    BotRuntimeState.username, BotRuntimeState.started_at, BotRuntimeState.updated_at
                )
            )
        ).first()
        if row is None or not row.username:
            return None
        changed_at = row.started_at or row.updated_at or await snapshots.db_now(session)
        await bus_events.bot_changed(session, row.username, changed_at)
        return str(row.username)


async def sync_bot_on_start(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Вызов при старте воркера: любой сбой — в лог (`bot_republish_failed`)."""
    try:
        username = await republish_bot(sessions)
        logger.info("bot_republished", published=username is not None)
    except Exception as exc:  # noqa: BLE001 — старт сервиса не зависит от шины
        logger.warning("bot_republish_failed", error=repr(exc))
