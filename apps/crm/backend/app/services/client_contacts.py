"""Контакты клиента (Q-011, Q-020): CRUD с аудитом и подсказки из подтверждённого Telegram.

Основной контакт — один на клиента: при отметке нового прежний снимается в той же транзакции,
частичный уникальный индекс `uq_client_contacts_primary` страхует от гонки.
"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contacts import contact_email, contact_phone, suggested_name
from app.domain.errors import NotFoundError, Reason, ValidationFailedError
from app.models.clients import Client, ClientContact
from app.models.leads import TelegramIdentity
from app.schemas.clients import ClientContacts, ContactIn, ContactOut, ContactSuggestion
from app.security import audit
from app.security.principal import Principal

AUDITED = ("full_name", "position", "phone_e164", "email", "is_primary", "telegram_identity_id")


def _values(body: ContactIn) -> dict[str, Any]:
    return {
        "full_name": body.full_name.strip(),
        "position": (body.position or "").strip() or None,
        "phone_e164": contact_phone(body.phone),
        "email": contact_email(body.email),
        "is_primary": body.is_primary,
        "note": (body.note or "").strip() or None,
        "telegram_identity_id": body.telegram_identity_id,
    }


def _snapshot(row: ClientContact) -> dict[str, Any]:
    return {k: getattr(row, k) for k in AUDITED}


class ClientContactService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def overview(self, client_id: int) -> ClientContacts:
        async with self._sessions() as session:
            await _client(session, client_id)
            rows = (
                await session.scalars(
                    select(ClientContact)
                    .where(ClientContact.client_id == client_id)
                    .order_by(ClientContact.is_primary.desc(), ClientContact.full_name)
                )
            ).all()
            identities = (
                await session.scalars(
                    select(TelegramIdentity)
                    .where(
                        TelegramIdentity.client_id == client_id,
                        TelegramIdentity.verified_at.is_not(None),
                        TelegramIdentity.phone_e164.is_not(None),
                    )
                    .order_by(TelegramIdentity.id)
                )
            ).all()
        linked = {r.telegram_identity_id for r in rows}
        phones = {r.phone_e164 for r in rows}
        suggestions = [
            ContactSuggestion(
                telegram_identity_id=i.id,
                tg_user_id=i.tg_user_id,
                tg_username=i.tg_username,
                full_name=suggested_name(i.tg_first_name, i.tg_username, i.phone_e164 or ""),
                phone_e164=i.phone_e164 or "",
            )
            for i in identities
            if i.id not in linked and i.phone_e164 not in phones
        ]
        return ClientContacts(
            contacts=[ContactOut.model_validate(r, from_attributes=True) for r in rows],
            suggestions=suggestions,
        )

    async def create(self, who: Principal, client_id: int, body: ContactIn) -> int:
        values = _values(body)
        async with self._sessions() as session, session.begin():
            await _client(session, client_id, lock=True)
            await _check_identity(session, client_id, values["telegram_identity_id"])
            if values["is_primary"]:
                await _clear_primary(session, client_id)
            row = ClientContact(client_id=client_id, **values)
            session.add(row)
            await session.flush()
            await audit.record(
                session,
                who.actor,
                "client.contact_create",
                "client",
                client_id,
                after={"contact_id": row.id, **_snapshot(row)},
            )
            return row.id

    async def update(
        self, who: Principal, client_id: int, contact_id: int, body: ContactIn
    ) -> None:
        values = _values(body)
        async with self._sessions() as session, session.begin():
            await _client(session, client_id, lock=True)
            row = await _contact(session, client_id, contact_id)
            await _check_identity(session, client_id, values["telegram_identity_id"])
            before = _snapshot(row)
            if values["is_primary"] and not row.is_primary:
                await _clear_primary(session, client_id)
            for key, value in values.items():
                setattr(row, key, value)
            await audit.record(
                session,
                who.actor,
                "client.contact_update",
                "client",
                client_id,
                before={"contact_id": contact_id, **before},
                after={"contact_id": contact_id, **_snapshot(row)},
            )

    async def delete(self, who: Principal, client_id: int, contact_id: int) -> None:
        async with self._sessions() as session, session.begin():
            row = await _contact(session, client_id, contact_id)
            before = _snapshot(row)
            await session.delete(row)
            await audit.record(
                session,
                who.actor,
                "client.contact_delete",
                "client",
                client_id,
                before={"contact_id": contact_id, **before},
            )


async def _client(session: AsyncSession, client_id: int, *, lock: bool = False) -> Client:
    client = await session.get(Client, client_id, with_for_update=lock)
    if client is None:
        raise NotFoundError("client not found")
    return client


async def _contact(session: AsyncSession, client_id: int, contact_id: int) -> ClientContact:
    row = await session.get(ClientContact, contact_id, with_for_update=True)
    if row is None or row.client_id != client_id:
        raise NotFoundError("contact not found")
    return row


async def _check_identity(session: AsyncSession, client_id: int, identity_id: int | None) -> None:
    """Связать можно только с подтверждённым Telegram-аккаунтом этого же клиента."""
    if identity_id is None:
        return
    identity = await session.get(TelegramIdentity, identity_id)
    if identity is None or identity.client_id != client_id or identity.verified_at is None:
        raise ValidationFailedError(
            "telegram account is not linked to this client",
            reason=Reason.TELEGRAM_NOT_LINKED,
            field="telegram_identity_id",
        )


async def _clear_primary(session: AsyncSession, client_id: int) -> None:
    await session.execute(
        update(ClientContact)
        .where(ClientContact.client_id == client_id, ClientContact.is_primary.is_(True))
        .values(is_primary=False)
    )
    await session.flush()
