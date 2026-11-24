"""Поиск лида/клиента по контактам и перенос истории при склейке (M3-CRM-05)."""

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.models.system import LlmUsage

# Та же пара, что `services/escalation.OPEN_STATUSES` (репозиторий не импортирует сервисы).
OPEN_STATUSES = ("open", "snoozed")


async def lead_by_phone(
    session: AsyncSession, phone: str, *, exclude_lead_id: int | None = None
) -> Lead | None:
    """Живой лид с этим номером: в карточке (`leads.phone_e164`) или в Telegram-идентичности."""
    via_identity = exists().where(
        TelegramIdentity.lead_id == Lead.id, TelegramIdentity.phone_e164 == phone
    )
    stmt = (
        select(Lead)
        .where(or_(Lead.phone_e164 == phone, via_identity), Lead.erased_at.is_(None))
        .order_by(Lead.created_at, Lead.id)
    )
    if exclude_lead_id is not None:
        stmt = stmt.where(Lead.id != exclude_lead_id)
    return (await session.scalars(stmt.limit(1))).first()


async def lead_by_email(session: AsyncSession, email: str) -> Lead | None:
    stmt = (
        select(Lead)
        .where(Lead.email == email, Lead.erased_at.is_(None))
        .order_by(Lead.created_at, Lead.id)
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def client_by_phone(session: AsyncSession, phone: str) -> tuple[int, str] | None:
    """Активный клиент, у которого есть контакт с таким номером: (id, название)."""
    stmt = (
        select(Client.id, Client.name)
        .join(ClientContact, ClientContact.client_id == Client.id)
        .where(ClientContact.phone_e164 == phone, Client.is_active.is_(True))
        .order_by(Client.id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return (int(row[0]), str(row[1])) if row is not None else None


async def has_open_escalation(session: AsyncSession, lead_id: int) -> bool:
    stmt = select(Escalation.id).where(
        Escalation.lead_id == lead_id, Escalation.status.in_(OPEN_STATUSES)
    )
    return (await session.scalars(stmt.limit(1))).first() is not None


async def active_escalation_ids(session: AsyncSession, lead_id: int) -> list[int]:
    stmt = select(Escalation.id).where(
        Escalation.lead_id == lead_id, Escalation.status.in_((*OPEN_STATUSES, "taken"))
    )
    return list((await session.scalars(stmt)).all())


async def repoint_lead_children(session: AsyncSession, from_id: int, to_id: int) -> list[str]:
    """Все строки, ссылающиеся на лид `from_id` (FK на `leads.id` + `llm_usage` без FK), → `to_id`.

    Идёт по метаданным моделей: новая таблица с FK на лида переносится автоматически.
    Возвращает имена затронутых таблиц (для аудита).
    """
    touched: list[str] = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name != "leads" or fk.column.name != "id":
                continue
            column = fk.parent
            result = await session.execute(
                update(table).where(column == from_id).values({column.name: to_id})
            )
            if (getattr(result, "rowcount", 0) or 0) > 0:
                touched.append(table.name)
    usage = await session.execute(
        update(LlmUsage).where(LlmUsage.lead_id == from_id).values(lead_id=to_id)
    )
    if (getattr(usage, "rowcount", 0) or 0) > 0:
        touched.append(LlmUsage.__tablename__)
    return touched


async def delete_lead_row(session: AsyncSession, lead_id: int) -> None:
    """Удаление поглощённой карточки ядром SQL (без ORM-каскадов: дети уже перенесены)."""
    await session.execute(delete(Lead).where(Lead.id == lead_id))


async def clients_by_contact(
    session: AsyncSession, *, phone: str | None, email: str | None
) -> list[tuple[int, str]]:
    """Active clients that have a contact with this phone or e-mail: [(id, name)], by id.

    Phone is compared as stored (E.164), e-mail case-insensitively. Distinct clients: one client
    with two matching contacts is one row.
    """
    conditions = []
    if phone:
        conditions.append(ClientContact.phone_e164 == phone)
    if email:
        conditions.append(func.lower(ClientContact.email) == email.lower())
    if not conditions:
        return []
    stmt = (
        select(Client.id, Client.name)
        .join(ClientContact, ClientContact.client_id == Client.id)
        .where(or_(*conditions), Client.is_active.is_(True))
        .group_by(Client.id, Client.name)
        .order_by(Client.id)
    )
    return [(int(row[0]), str(row[1])) for row in (await session.execute(stmt)).all()]


async def open_lead_of_client(session: AsyncSession, client_id: int) -> Lead | None:
    """The latest living lead of the client that is still in play (not lost / unresponsive)."""
    stmt = (
        select(Lead)
        .where(
            Lead.client_id == client_id,
            Lead.erased_at.is_(None),
            Lead.stage.notin_(("lost", "unresponsive")),
        )
        .order_by(Lead.id.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def exact_client_of_contact(
    session: AsyncSession, *, phone: str | None, email: str | None
) -> int | None:
    """Client id when ALL given contacts belong to ONE contact of ONE client, else None.

    Both phone and e-mail given → the same client contact row must carry both; one given → it
    must point to one client.
    """
    if not phone and not email:
        return None
    stmt = (
        select(Client.id)
        .join(ClientContact, ClientContact.client_id == Client.id)
        .where(Client.is_active.is_(True))
        .distinct()
    )
    if phone:
        stmt = stmt.where(ClientContact.phone_e164 == phone)
    if email:
        stmt = stmt.where(func.lower(ClientContact.email) == email.lower())
    ids = list((await session.scalars(stmt.limit(2))).all())
    return int(ids[0]) if len(ids) == 1 else None
