"""Склейка Telegram-лида с лидом по номеру (M3-CRM-05, ARCHITECTURE §17).

Вызывается из `ClientBotService.save_phone` в той же транзакции: лид поделился номером, и такой
номер уже есть у лида с сайта/звонка/почты. Правило — `domain/lead_sources.merge_plan`; здесь —
применение: поля выжившего, перенос истории (переписка, идентичности, передачи, заметки, сделки,
переходы, прогоны квалификатора, запросы, учёт моделей), удаление поглощённой карточки, аудит.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.lead_sources import LeadFacts, MergePlan, merge_plan
from app.domain.stages import TransitionSource
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation, StageTransition
from app.repositories import events
from app.repositories import lead_intake as repo
from app.repositories import leads as leads_repo
from app.security import audit

logger = structlog.get_logger(__name__)

MERGE_FIELDS = (
    "source",
    "stage",
    "score",
    "owner_mode",
    "assigned_user_id",
    "language",
    "language_confirmed",
    "display_name",
    "need_summary",
    "consent_given_at",
    "product_interest",
    "qualification",
    "company_name",
    "email",
    "phone_e164",
    "client_id",
)


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    survivor_id: int
    absorbed_id: int
    # Активные передачи на выжившем после склейки — их карточки в канале перерисовать.
    escalation_ids: tuple[int, ...]


def _snapshot(lead: Lead) -> dict[str, Any]:
    """Поля для аудита (JSONB): даты — строками ISO."""
    data: dict[str, Any] = {"id": lead.id}
    for name in MERGE_FIELDS:
        value = getattr(lead, name)
        data[name] = value.isoformat() if isinstance(value, datetime) else value
    return data


async def _facts(session: AsyncSession, lead: Lead) -> LeadFacts:
    return LeadFacts(
        id=lead.id,
        created_at=lead.created_at,
        source=lead.source,
        stage=lead.stage,
        score=lead.score,
        owner_mode=lead.owner_mode,
        assigned_user_id=lead.assigned_user_id,
        language=lead.language,
        language_confirmed=bool(lead.language_confirmed),
        display_name=lead.display_name or "",
        need_summary=lead.need_summary,
        consent_given_at=lead.consent_given_at,
        product_interest=tuple(lead.product_interest or ()),
        qualification=dict(lead.qualification or {}),
        company_name=lead.company_name,
        email=lead.email,
        phone_e164=lead.phone_e164,
        client_id=lead.client_id,
        has_open_escalation=await repo.has_open_escalation(session, lead.id),
    )


def _apply(lead: Lead, plan: MergePlan) -> None:
    lead.source = plan.source
    lead.score = plan.score
    lead.owner_mode = plan.owner_mode
    lead.assigned_user_id = plan.assigned_user_id
    lead.language = plan.language
    lead.language_confirmed = plan.language_confirmed
    lead.display_name = plan.display_name
    lead.need_summary = plan.need_summary
    lead.consent_given_at = plan.consent_given_at
    lead.product_interest = list(plan.product_interest)
    lead.qualification = plan.qualification
    lead.company_name = plan.company_name
    lead.email = plan.email
    lead.phone_e164 = plan.phone_e164
    lead.client_id = plan.client_id


async def merge_by_phone(
    session: AsyncSession, identity: TelegramIdentity, phone: str
) -> MergeOutcome | None:
    """Лид идентичности и лид с тем же номером → одна карточка; None — склеивать не с кем."""
    if identity.lead_id is None:
        return None
    mine = await leads_repo.get_lead(session, identity.lead_id, for_update=True)
    if mine is None or mine.erased_at is not None:
        return None
    other = await repo.lead_by_phone(session, phone, exclude_lead_id=mine.id)
    if other is None:
        return None
    other = await leads_repo.get_lead(session, other.id, for_update=True)
    if other is None or other.erased_at is not None:
        return None
    plan = merge_plan(await _facts(session, mine), await _facts(session, other))
    survivor, absorbed = (mine, other) if plan.survivor_id == mine.id else (other, mine)
    before = {"survivor": _snapshot(survivor), "absorbed": _snapshot(absorbed)}
    now = datetime.now(UTC)
    if plan.close_absorbed_escalation:
        await session.execute(
            update(Escalation)
            .where(Escalation.lead_id == absorbed.id, Escalation.status.in_(repo.OPEN_STATUSES))
            .values(status="closed", resolved_at=now, outcome="merged")
        )
    _apply(survivor, plan)
    if plan.stage_changed:
        survivor.stage = plan.stage.value
        session.add(
            StageTransition(
                lead_id=survivor.id,
                from_stage=before["survivor"]["stage"],
                to_stage=plan.stage.value,
                source=TransitionSource.SYSTEM.value,
                reason=f"merged with lead #{absorbed.id}",
            )
        )
    survivor.notes_count += absorbed.notes_count
    await session.flush()
    touched = await repo.repoint_lead_children(session, absorbed.id, survivor.id)
    await repo.delete_lead_row(session, absorbed.id)
    session.expunge(absorbed)
    await audit.record(
        session,
        audit.Actor.system(),
        "lead.merge",
        "lead",
        survivor.id,
        before=before,
        after={**_snapshot(survivor), "moved": touched},
    )
    await events.publish(
        session, "lead.updated", lead_id=survivor.id, owner_mode=survivor.owner_mode
    )
    await events.publish(session, "lead.updated", lead_id=absorbed.id, merged_into=survivor.id)
    logger.info("lead_merged", lead_id=survivor.id, absorbed_lead_id=absorbed.id, phone_set=True)
    if plan.stage_changed:
        await bus_events.lead_stage_changed(
            session,
            survivor,
            from_stage=before["survivor"]["stage"],
            to_stage=plan.stage.value,
            actor=audit.Actor.system(),
            reason=f"merged with lead #{absorbed.id}",
        )
    else:
        await bus_events.lead_updated(session, survivor, audit.Actor.system())
    escalations = await repo.active_escalation_ids(session, survivor.id)
    return MergeOutcome(survivor.id, absorbed.id, tuple(escalations))
