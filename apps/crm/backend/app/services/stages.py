"""Применение переходов стадий через state machine (SPEC §6.2)."""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.stage_machine import TransitionDecision, decide
from app.domain.stages import Stage, TransitionSource
from app.models.leads import Lead
from app.models.qualification import StageTransition
from app.repositories import events
from app.security.audit import Actor
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
        await bus_events.lead_stage_changed(
            session,
            lead,
            from_stage=decision.from_stage.value,
            to_stage=target.value,
            actor=_actor(source, actor_user_id),
            reason=reason,
        )
        await events.publish(session, "lead.updated", lead_id=lead.id, stage=target.value)
        if target == Stage.QUALIFIED:
            # Q-021: квалифицированный лид — открытая сделка (идемпотентно, одна на лида).
            await deals.ensure_open_deal(session, lead)
    return decision


def _actor(source: TransitionSource, actor_user_id: int | None) -> Actor:
    """Кто сменил стадию: сотрудник, квалификатор бота или система (таймеры, триггеры)."""
    if actor_user_id is not None:
        return Actor(actor_user_id, "user")
    if source in (TransitionSource.QUALIFIER, TransitionSource.TRIGGER):
        return Actor(None, "bot")
    return Actor.system()


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
