"""Вспомогательные функции действий над лидом (вынесены из `services/leads.py`, ≤ 400 строк)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stages import Stage
from app.models.leads import Lead, LeadNote
from app.models.qualification import StageTransition
from app.repositories import users as users_repo
from app.security.principal import Principal


async def history(session: AsyncSession, lead_id: int) -> list[tuple[Stage, Stage]]:
    stmt = (
        select(StageTransition.from_stage, StageTransition.to_stage)
        .where(StageTransition.lead_id == lead_id)
        .order_by(StageTransition.id)
    )
    return [(Stage(a), Stage(b)) for a, b in (await session.execute(stmt)).all()]


def add_note(
    session: AsyncSession, lead: Lead, who: Principal, text: str, *, visible_to_bot: bool
) -> LeadNote:
    note = LeadNote(
        lead_id=lead.id,
        user_id=who.user_id,
        text=text.strip()[:4000],
        visible_to_bot=visible_to_bot,
    )
    session.add(note)
    lead.notes_count += 1
    return note


def snapshot(lead: Lead) -> dict[str, Any]:
    return {
        "stage": lead.stage,
        "owner_mode": lead.owner_mode,
        "assigned_user_id": lead.assigned_user_id,
    }


async def user_name(session: AsyncSession, user_id: int | None) -> str | None:
    """Имя того, кто ведёт лида, — для «Лида уже забрал …» (имена команды видны всем ролям)."""
    user = await users_repo.get(session, user_id) if user_id is not None else None
    return user.full_name if user is not None else None
