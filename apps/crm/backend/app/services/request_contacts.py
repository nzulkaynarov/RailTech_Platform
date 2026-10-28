"""Контакт заявки «Создать заявку» (CRM-03, W16-D1-2): контакт клиента или новый с каналом.

E-mail не обязателен — нужен хотя бы один канал: телефон, e-mail или Telegram лида (422
`contact_channel_required`).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.client_requests import contact_channels
from app.domain.errors import Reason, ValidationFailedError
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.schemas.client_requests import RequestContactIn
from app.security.principal import Principal


async def _lead_identity(session: AsyncSession, lead: Lead | None) -> TelegramIdentity | None:
    if lead is None:
        return None
    return await session.scalar(
        select(TelegramIdentity)
        .where(TelegramIdentity.lead_id == lead.id)
        .order_by(TelegramIdentity.id)
        .limit(1)
    )


async def request_contact(
    session: AsyncSession, client: Client, lead: Lead | None, data: RequestContactIn, who: Principal
) -> ClientContact:
    """Контакт заявки: существующий контакт клиента или новый; хотя бы один канал — иначе 422."""
    if data.contact_id is not None:
        contact = await session.get(ClientContact, data.contact_id)
        if contact is None or contact.client_id != client.id:
            raise ValidationFailedError(
                "contact does not belong to the client", field="contact.contact_id"
            )
    else:
        identity = await _lead_identity(session, lead) if data.use_lead_telegram else None
        has_primary = await session.scalar(
            select(ClientContact.id)
            .where(ClientContact.client_id == client.id, ClientContact.is_primary)
            .limit(1)
        )
        contact = ClientContact(
            client_id=client.id,
            full_name=(data.full_name or "").strip(),
            position=(data.position or "").strip() or None,
            phone_e164=(data.phone or "").strip() or (identity.phone_e164 if identity else None),
            email=(data.email or "").strip().lower() or None,
            telegram_identity_id=identity.id if identity else None,
            is_primary=has_primary is None,
        )
    channels = contact_channels(
        phone=contact.phone_e164,
        email=contact.email,
        telegram=contact.telegram_identity_id is not None,
    )
    if not channels:
        raise ValidationFailedError(
            "the contact needs a phone, an e-mail or telegram",
            reason=Reason.CONTACT_CHANNEL_REQUIRED,
            field="contact",
        )
    if contact.id is None:
        session.add(contact)
        await session.flush()
        await bus_events.contact_created(session, contact, who.actor)
    return contact
