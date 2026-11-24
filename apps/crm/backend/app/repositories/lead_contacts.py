"""Дубли при правке контактов лида (LH-1): другой лид или клиент с тем же номером или почтой."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity


@dataclass(frozen=True, slots=True)
class Duplicate:
    kind: Literal["lead", "client"]
    id: int
    name: str
    field: Literal["phone", "email"]


async def lead_with_phone(session: AsyncSession, phone: str, exclude_lead_id: int) -> Lead | None:
    """Живой неотброшенный лид с этим номером (карточка или Telegram-идентичность), кроме себя."""
    via_identity = exists().where(
        TelegramIdentity.lead_id == Lead.id, TelegramIdentity.phone_e164 == phone
    )
    stmt = (
        select(Lead)
        .where(
            or_(Lead.phone_e164 == phone, via_identity),
            Lead.erased_at.is_(None),
            Lead.discarded_kind.is_(None),
            Lead.source != SANDBOX_SOURCE,
            Lead.id != exclude_lead_id,
        )
        .order_by(Lead.created_at, Lead.id)
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def lead_with_email(session: AsyncSession, email: str, exclude_lead_id: int) -> Lead | None:
    stmt = (
        select(Lead)
        .where(
            Lead.email == email,
            Lead.erased_at.is_(None),
            Lead.discarded_kind.is_(None),
            Lead.source != SANDBOX_SOURCE,
            Lead.id != exclude_lead_id,
        )
        .order_by(Lead.created_at, Lead.id)
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def client_with_contact(
    session: AsyncSession, field: Literal["phone", "email"], value: str
) -> tuple[int, str] | None:
    """Активный клиент, у которого есть контакт с этим номером или почтой: (id, название)."""
    column = ClientContact.phone_e164 if field == "phone" else func.lower(ClientContact.email)
    stmt = (
        select(Client.id, Client.name)
        .join(ClientContact, ClientContact.client_id == Client.id)
        .where(column == value, Client.is_active.is_(True))
        .order_by(Client.id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return (int(row[0]), str(row[1])) if row is not None else None


async def duplicates(
    session: AsyncSession, lead_id: int, phone: str | None, email: str | None
) -> list[Duplicate]:
    """Что уже есть с этим номером или почтой: лид и клиент; пусто — дублей нет."""
    found: list[Duplicate] = []
    for field, value in (("phone", phone), ("email", email)):
        if not value:
            continue
        lead = (
            await lead_with_phone(session, value, lead_id)
            if field == "phone"
            else await lead_with_email(session, value, lead_id)
        )
        if lead is not None:
            found.append(Duplicate("lead", lead.id, lead.display_name, field))  # type: ignore[arg-type]
        client = await client_with_contact(session, field, value)  # type: ignore[arg-type]
        if client is not None:
            found.append(Duplicate("client", client[0], client[1], field))  # type: ignore[arg-type]
    return found
