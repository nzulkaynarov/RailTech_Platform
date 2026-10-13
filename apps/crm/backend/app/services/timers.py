"""Таймеры лидов (SPEC §6.2): перевод в `unresponsive`.

Лид «молчит», если последним писали мы (бот или менеджер), а от лида нет
сообщений `bot.unresponsive_days` суток. Возврат в `engaged` — при новом
сообщении лида (`ConversationService`).
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.sandbox import SANDBOX_SOURCE
from app.domain.stages import Stage, TransitionSource
from app.models.leads import Lead
from app.services import stages
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

TIMER_STAGES = (Stage.NEW, Stage.ENGAGED, Stage.QUALIFIED)  # не handoff (ADR-0015)
BATCH = 500


async def mark_unresponsive(
    sessions: async_sessionmaker[AsyncSession], settings: SettingsService, now: datetime
) -> int:
    cfg = await settings.get()
    cutoff = now - timedelta(days=cfg.bot.unresponsive_days)
    last_ours = func.greatest(Lead.last_bot_msg_at, Lead.last_human_msg_at)
    stmt = (
        select(Lead)
        .where(
            Lead.stage.in_([s.value for s in TIMER_STAGES]),
            Lead.erased_at.is_(None),
            Lead.source != SANDBOX_SOURCE,
            Lead.last_lead_msg_at < cutoff,
            last_ours > Lead.last_lead_msg_at,
        )
        .order_by(Lead.id)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    )
    moved = 0
    async with sessions() as session, session.begin():
        for lead in (await session.scalars(stmt)).all():
            decision = await stages.transition(
                session,
                lead,
                Stage.UNRESPONSIVE,
                TransitionSource.TIMER,
                reason=f"no reply for {cfg.bot.unresponsive_days} days",
            )
            moved += int(decision.changed)
    logger.info("leads_marked_unresponsive", count=moved)
    return moved
