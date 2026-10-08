"""Чтение данных для CRM: список лидов с фильтрами, карточка, переписка, входящие."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leads import Conversation, Lead, LeadNote, Message, TelegramIdentity
from app.models.qualification import Escalation

ACTIVE = ("open", "snoozed", "taken")
PRIORITY_RANK = {"hot": 0, "warm": 1, "info": 2}


@dataclass(frozen=True, slots=True)
class LeadFilter:
    stage: str | None = None
    owner: str | None = None  # "me" | "none" | str(user_id)
    min_score: int | None = None
    language: str | None = None
    q: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


def _filtered(f: LeadFilter, me: int) -> Select[Lead]:
    stmt = select(Lead).where(Lead.erased_at.is_(None))
    if f.stage:
        stmt = stmt.where(Lead.stage.in_(f.stage.split(",")))
    if f.owner == "me":
        stmt = stmt.where(Lead.assigned_user_id == me)
    elif f.owner == "none":
        stmt = stmt.where(Lead.assigned_user_id.is_(None))
    elif f.owner and f.owner.isdigit():
        stmt = stmt.where(Lead.assigned_user_id == int(f.owner))
    if f.min_score is not None:
        stmt = stmt.where(Lead.score >= f.min_score)
    if f.language:
        stmt = stmt.where(Lead.language == f.language)
    if f.q:
        pattern = f"%{f.q.strip()}%"
        stmt = stmt.where(or_(Lead.display_name.ilike(pattern), Lead.need_summary.ilike(pattern)))
    if f.created_from:
        stmt = stmt.where(Lead.created_at >= f.created_from)
    if f.created_to:
        stmt = stmt.where(Lead.created_at < f.created_to)
    return stmt


async def list_leads(
    session: AsyncSession, f: LeadFilter, me: int, limit: int, offset: int, sort: str
) -> tuple[Sequence[Lead], int]:
    stmt = _filtered(f, me)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    orders: dict[str, ColumnElement[Any]] = {
        "score": Lead.score.desc(),
        "created": Lead.created_at.desc(),
    }
    order = orders.get(sort, Lead.last_lead_msg_at.desc().nulls_last())
    rows = (
        await session.scalars(stmt.order_by(order, Lead.id.desc()).limit(limit).offset(offset))
    ).all()
    return rows, total


async def active_escalations(
    session: AsyncSession, lead_ids: Sequence[int]
) -> dict[int, Escalation]:
    if not lead_ids:
        return {}
    stmt = (
        select(Escalation)
        .where(Escalation.lead_id.in_(lead_ids), Escalation.status.in_(ACTIVE))
        .order_by(Escalation.id)
    )
    return {e.lead_id: e for e in (await session.scalars(stmt)).all()}


async def inbox(session: AsyncSession, me: int) -> tuple[list[Lead], list[Lead], list[Lead]]:
    escalated = (
        await session.scalars(
            select(Lead)
            .join(Escalation, Escalation.lead_id == Lead.id)
            .where(Escalation.status.in_(("open", "snoozed")), Lead.erased_at.is_(None))
            .order_by(Escalation.created_at)
        )
    ).all()
    mine = (
        await session.scalars(
            select(Lead)
            .where(
                Lead.assigned_user_id == me, Lead.owner_mode == "human", Lead.erased_at.is_(None)
            )
            .order_by(Lead.last_lead_msg_at.desc().nulls_last())
            .limit(100)
        )
    ).all()
    unassigned = (
        await session.scalars(
            select(Lead)
            .where(
                Lead.owner_mode == "paused",
                Lead.assigned_user_id.is_(None),
                Lead.erased_at.is_(None),
            )
            .order_by(Lead.last_lead_msg_at.desc().nulls_last())
            .limit(100)
        )
    ).all()
    return list(escalated), list(mine), list(unassigned)


async def messages(
    session: AsyncSession, lead_id: int, limit: int, before_id: int | None
) -> list[Message]:
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = (await session.scalars(stmt.order_by(Message.id.desc()).limit(limit))).all()
    return list(reversed(rows))


async def notes(session: AsyncSession, lead_id: int) -> Sequence[LeadNote]:
    stmt = select(LeadNote).where(LeadNote.lead_id == lead_id).order_by(LeadNote.id.desc())
    return (await session.scalars(stmt)).all()


async def tg_username(session: AsyncSession, lead_id: int) -> str | None:
    stmt = select(TelegramIdentity.tg_username).where(TelegramIdentity.lead_id == lead_id)
    value: str | None = (await session.scalars(stmt)).first()
    return value
