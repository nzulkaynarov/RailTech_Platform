"""Применение переходов стадий через state machine (SPEC §6.2)."""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stage_machine import TransitionDecision, decide
from app.domain.stages import Stage, TransitionSource
from app.models.leads import Lead
from app.models.qualification import StageTransition
from app.repositories import events
from app.services import deals

logger = structlog.get_logger(__name__)


async def transition(
    session: AsyncSession,
    lead: Lead,
    target: Stage,
    source: TransitionSource,
    *,
    reason: str,
    actor_user_id: int | None = None,
) -> TransitionDecision:
    """Меняет стадию, если переход разрешён; журнал — `stage_transitions`."""
    decision = decide(Stage(lead.stage), target, source)
    if not decision.allowed:
        logger.info("stage_transition_rejected", lead_id=lead.id, reason=decision.reason)
        return decision
    if decision.changed:
        lead.stage = target.value
        if target == Stage.UNRESPONSIVE:
            lead.unresponsive_since = datetime.now(UTC)
        await _journal(session, lead.id, decision, source, reason, actor_user_id)
        await events.publish(session, "lead.updated", lead_id=lead.id, stage=target.value)
        if target == Stage.QUALIFIED:
            # Q-021: квалифицированный лид — открытая сделка (идемпотентно, одна на лида).
            await deals.ensure_open_deal(session, lead)
    return decision


async def _journal(
    session: AsyncSession,
    lead_id: int,
    decision: TransitionDecision,
    source: TransitionSource,
    reason: str,
    actor_user_id: int | None,
) -> None:
    session.add(
        StageTransition(
            lead_id=lead_id,
            from_stage=decision.from_stage.value,
            to_stage=decision.to_stage.value,
            source=source.value,
            actor_user_id=actor_user_id,
            reason=reason[:500],
        )
    )
