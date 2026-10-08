"""Применение эскалации (SPEC §8.2) в транзакции вызывающего.

План строит домен (`domain/escalation.py`); здесь — запись `escalations`,
переход в `handoff`, пауза бота. Текст лиду и пост в канал выполняет
вызывающий после коммита (уведомления в канал — Фаза 4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.business_hours import add_business_minutes, is_business_time
from app.domain.escalation import EscalationPlan, OpenEscalation, plan
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.triggers import Priority, TriggerCode, TriggerHit
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import events
from app.schemas.settings import AppSettings
from app.services import stages

logger = structlog.get_logger(__name__)

OPEN_STATUSES = ("open", "snoozed")


@dataclass(frozen=True, slots=True)
class AppliedEscalation:
    escalation_id: int
    plan: EscalationPlan


async def open_escalation(session: AsyncSession, lead_id: int) -> Escalation | None:
    stmt = (
        select(Escalation)
        .where(Escalation.lead_id == lead_id, Escalation.status.in_(OPEN_STATUSES))
        .with_for_update()
    )
    return (await session.scalars(stmt)).first()


async def apply(
    session: AsyncSession,
    lead: Lead,
    hits: Sequence[TriggerHit],
    cfg: AppSettings,
    now: datetime,
    *,
    reason_text: str | None = None,
    recommendation: str | None = None,
) -> AppliedEscalation | None:
    """Создать или дополнить открытую эскалацию лида. None — эскалация не нужна."""
    current = await open_escalation(session, lead.id)
    hours = cfg.business_hours.domain()
    escalation_plan = plan(
        hits,
        stage=Stage(lead.stage),
        owner_mode=OwnerMode(lead.owner_mode),
        open_escalation=_snapshot(current),
        business_time=is_business_time(now, hours),
    )
    if escalation_plan is None:
        return None
    codes = [c.value for c in escalation_plan.reason_codes]
    if current is None:
        current = Escalation(
            lead_id=lead.id,
            reason_codes=codes,
            reason_text=reason_text,
            recommendation=recommendation,
            priority=escalation_plan.priority.value,
            status="open",
            sla_due_at=add_business_minutes(now, cfg.escalation.sla_minutes, hours),
        )
        session.add(current)
    else:
        current.reason_codes = codes
        current.priority = escalation_plan.priority.value
        current.reason_text = reason_text or current.reason_text
        current.recommendation = recommendation or current.recommendation
    if escalation_plan.move_to_handoff:
        await stages.transition(
            session, lead, Stage.HANDOFF, TransitionSource.TRIGGER, reason=", ".join(codes)
        )
    if escalation_plan.pause_bot:
        lead.owner_mode = OwnerMode.PAUSED.value
    if escalation_plan.lead_text is not None:
        lead.handoff_notice_sent_at = now
    await session.flush()
    await events.publish(
        session,
        "escalation.updated",
        lead_id=lead.id,
        escalation_id=current.id,
        priority=escalation_plan.priority.value,
    )
    logger.info(
        "escalation_applied",
        lead_id=lead.id,
        escalation_id=current.id,
        codes=codes,
        priority=escalation_plan.priority.value,
        is_new=escalation_plan.is_new,
    )
    return AppliedEscalation(current.id, escalation_plan)


def _snapshot(row: Escalation | None) -> OpenEscalation | None:
    if row is None:
        return None
    return OpenEscalation(
        reason_codes=tuple(TriggerCode(c) for c in row.reason_codes if c in _KNOWN),
        priority=Priority(row.priority),
    )


_KNOWN = frozenset(c.value for c in TriggerCode)
