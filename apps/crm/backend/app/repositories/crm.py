"""Чтение данных для CRM: список лидов с фильтрами, карточка, переписка, входящие."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.auth import User
from app.models.clients import ClientContact
from app.models.kb import Product
from app.models.leads import Conversation, Lead, LeadNote, Message, TelegramIdentity
from app.models.qualification import Escalation

ACTIVE = ("open", "snoozed", "taken")
_waits_for_reply = func.coalesce(
    Lead.last_lead_msg_at > func.coalesce(Lead.last_human_msg_at, Lead.created_at), False
)
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
    stmt = select(Lead).where(Lead.erased_at.is_(None), Lead.source != SANDBOX_SOURCE)
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


async def user_names(session: AsyncSession, leads: Sequence[Lead]) -> dict[int, str]:
    """Имена владельцев лидов: менеджеру и наблюдателю `/users` недоступен, а «кто ведёт» нужен."""
    ids = {lead.assigned_user_id for lead in leads if lead.assigned_user_id is not None}
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {user_id: name for user_id, name in rows}  # noqa: C416 — Row, не кортеж


async def inbox(session: AsyncSession, me: int) -> tuple[list[Lead], list[Lead], list[Lead]]:
    escalated = (
        await session.scalars(
            select(Lead)
            .join(Escalation, Escalation.lead_id == Lead.id)
            .where(
                Escalation.status.in_(("open", "snoozed")),
                Lead.erased_at.is_(None),
                Lead.source != SANDBOX_SOURCE,
            )
            .order_by(Escalation.created_at)
        )
    ).all()
    mine = (
        await session.scalars(
            select(Lead)
            .where(
                Lead.assigned_user_id == me,
                Lead.owner_mode == "human",
                Lead.erased_at.is_(None),
                Lead.source != SANDBOX_SOURCE,
            )
            # Сначала те, кто ждёт ответа: лид написал после последнего ответа менеджера.
            .order_by(_waits_for_reply.desc(), Lead.last_lead_msg_at.desc().nulls_last())
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
                Lead.source != SANDBOX_SOURCE,
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


async def lead_message(session: AsyncSession, lead_id: int, message_id: int) -> Message | None:
    """Сообщение переписки именно этого лида (чужой id — None, как несуществующий)."""
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id, Message.id == message_id)
    )
    found: Message | None = (await session.scalars(stmt.limit(1))).first()
    return found


async def reply_by_key(
    session: AsyncSession, lead_id: int, client_message_id: str
) -> Message | None:
    """Ответ менеджера с этим ключом повтора (D1-1: «Повторить» не дублирует); `meta.delivery` —
    `sending` (отправка идёт или её итог неизвестен) или `sent`."""
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.lead_id == lead_id,
            Message.role == "manager",
            Message.meta["client_message_id"].astext == client_message_id,
        )
        .order_by(Message.id)
        .limit(1)
    )
    found: Message | None = (await session.scalars(stmt)).first()
    return found


async def last_lead_texts(session: AsyncSession, lead_ids: Sequence[int]) -> dict[int, str]:
    """Последнее непустое сообщение лида — по одному на лида, одним запросом (записка передачи)."""
    if not lead_ids:
        return {}
    latest = (
        select(func.max(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id.in_(lead_ids), Message.role == "lead", Message.text != "")
        .group_by(Conversation.lead_id)
    )
    stmt = (
        select(Conversation.lead_id, Message.text)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id.in_(latest))
    )
    return {row.lead_id: row.text for row in (await session.execute(stmt)).all()}


async def product_names(session: AsyncSession, keys: Sequence[str]) -> dict[str, str]:
    if not keys:
        return {}
    stmt = select(Product.key, Product.name).where(Product.key.in_(set(keys)))
    return {row.key: row.name for row in (await session.execute(stmt)).all()}


async def notes(session: AsyncSession, lead_id: int) -> Sequence[LeadNote]:
    stmt = select(LeadNote).where(LeadNote.lead_id == lead_id).order_by(LeadNote.id.desc())
    return (await session.scalars(stmt)).all()


async def tg_username(session: AsyncSession, lead_id: int) -> str | None:
    stmt = select(TelegramIdentity.tg_username).where(TelegramIdentity.lead_id == lead_id)
    value: str | None = (await session.scalars(stmt)).first()
    return value


async def tg_phone(session: AsyncSession, lead_id: int) -> str | None:
    """Номер, которым лид поделился кнопкой в боте (Q-020), E.164."""
    stmt = select(TelegramIdentity.phone_e164).where(TelegramIdentity.lead_id == lead_id)
    value: str | None = (await session.scalars(stmt)).first()
    return value


async def client_primary_phone(session: AsyncSession, client_id: int | None) -> str | None:
    """Телефон основного контакта клиента лида (Q-011) — рядом с номером из Telegram."""
    if client_id is None:
        return None
    stmt = select(ClientContact.phone_e164).where(
        ClientContact.client_id == client_id, ClientContact.is_primary.is_(True)
    )
    value: str | None = (await session.scalars(stmt)).first()
    return value
