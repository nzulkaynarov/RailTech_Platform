"""Данные для постов канала команды: карточка из БД, упоминания, ссылки на CRM (SPEC §9.1)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Role, User, UserRole
from app.models.kb import Product
from app.models.leads import Conversation, Lead, Message, TelegramIdentity
from app.models.qualification import Escalation
from app.schemas.settings import AppSettings
from app.services import channel_texts as tx
from app.services.channel_card import CardData

# Дежурных нет → упоминаем активных менеджеров с Telegram, но не больше стольких.
MENTION_CAP: Final = 5


def lead_link(cfg: AppSettings, lead_id: int) -> str:
    url = f"{cfg.company.crm_base_url.rstrip('/')}/leads/{lead_id}"
    return tx.LEAD_LINK.format(url=escape(url, quote=True), lead_id=lead_id)


async def load_card(
    session: AsyncSession, escalation_id: int, cfg: AppSettings
) -> tuple[Escalation, CardData] | None:
    escalation = await session.get(Escalation, escalation_id)
    if escalation is None:
        return None
    lead = await session.get(Lead, escalation.lead_id)
    if lead is None:
        return None
    taken_by = await _name(session, escalation.taken_by_user_id)
    stored: dict[str, Any] = dict(lead.qualification or {})
    interest = list(lead.product_interest or [])
    card = CardData(
        lead_id=lead.id,
        display_name=lead.display_name,
        language=lead.language,
        score=lead.score,
        stage=lead.stage,
        need_summary=lead.need_summary,
        product_interest=interest,
        timeline=stored.get("timeline"),
        decision_role=stored.get("decision_role"),
        priority=escalation.priority,
        reason_codes=list(escalation.reason_codes or []),
        reason_text=escalation.reason_text,
        recommendation=escalation.recommendation,
        status=escalation.status,
        taken_by=taken_by,
        taken_at=escalation.taken_at,
        sla_overdue=escalation.sla_notified_at is not None,
        last_lead_message=await _last_lead_text(session, lead.id),
        crm_url=f"{cfg.company.crm_base_url.rstrip('/')}/leads/{lead.id}",
        timezone=cfg.business_hours.timezone,
        kb_gap_streak=cfg.escalation.kb_gap_streak,
        created_at=escalation.created_at,
        now=datetime.now(UTC),
        snoozed_until=escalation.snoozed_until,
        snoozed_by=await _name(session, lead.assigned_user_id),
        product_names=await _product_names(session, interest),
        escalation_id=escalation.id,
        phone=await _phone(session, lead.id),
    )
    return escalation, card


async def mentions(session: AsyncSession, duty_user_ids: Sequence[int]) -> str:
    """Дежурные; если их нет — активные менеджеры с привязанным Telegram (до MENTION_CAP)."""
    if duty_user_ids:
        stmt = select(User).where(User.id.in_(duty_user_ids), User.is_active.is_(True))
    else:
        stmt = (
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "manager", User.is_active.is_(True), User.tg_user_id.is_not(None))
            .order_by(User.id)
            .limit(MENTION_CAP)
        )
    users = (await session.scalars(stmt)).unique().all()
    return " ".join(
        f'<a href="tg://user?id={u.tg_user_id}">{escape(u.full_name)}</a>'
        for u in users
        if u.tg_user_id
    )


async def _name(session: AsyncSession, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user.full_name if user else None


async def _product_names(session: AsyncSession, keys: Sequence[str]) -> dict[str, str]:
    if not keys:
        return {}
    rows = await session.execute(select(Product.key, Product.name).where(Product.key.in_(keys)))
    return {row.key: row.name for row in rows.all()}


async def _phone(session: AsyncSession, lead_id: int) -> str | None:
    stmt = select(TelegramIdentity.phone_e164).where(
        TelegramIdentity.lead_id == lead_id, TelegramIdentity.phone_e164.is_not(None)
    )
    value: str | None = (await session.scalars(stmt.limit(1))).first()
    return value


async def _last_lead_text(session: AsyncSession, lead_id: int) -> str | None:
    stmt = (
        select(Message.text)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id, Message.role == "lead", Message.text != "")
        .order_by(Message.id.desc())
        .limit(1)
    )
    value: str | None = await session.scalar(stmt)
    return value
