"""Почта и телефон, добавленные в карточке лида, доходят до контакта компании (КОНТР-1а).

Лид привязан к компании (`leads.client_id`), а человек у неё уже контакт: правка его почты или
телефона в карточке лида переносится в этот контакт и уходит событием `contact.updated` — ERP
получает контакт с почтой и может пригласить его в кабинет. Контакт — тот, что связан с
Telegram лида, иначе основной, иначе единственный; неоднозначно — ничего не пишем. Пустое значение
контакт не стирает.
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.models.clients import ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.security import audit
from app.security.audit import Actor


async def _contact_of(session: AsyncSession, lead: Lead) -> ClientContact | None:
    contacts = list(
        (
            await session.scalars(
                select(ClientContact)
                .where(ClientContact.client_id == lead.client_id)
                .order_by(ClientContact.id)
            )
        ).all()
    )
    identities = set(
        (
            await session.scalars(
                select(TelegramIdentity.id).where(TelegramIdentity.lead_id == lead.id)
            )
        ).all()
    )
    linked = [c for c in contacts if c.telegram_identity_id in identities]
    if len(linked) == 1:
        return linked[0]
    if linked:
        return None
    primary = [c for c in contacts if c.is_primary]
    if len(primary) == 1:
        return primary[0]
    return contacts[0] if len(contacts) == 1 else None


async def sync_to_contact(
    session: AsyncSession, lead: Lead, changed: Collection[str], actor: Actor
) -> bool:
    """Переносит изменённые почту и телефон лида в контакт его компании; `True` — изменён."""
    if lead.client_id is None or not ({"email", "phone"} & set(changed)):
        return False
    contact = await _contact_of(session, lead)
    if contact is None:
        return False
    before = {"email": contact.email, "phone_e164": contact.phone_e164}
    if "email" in changed and lead.email:
        contact.email = lead.email
    if "phone" in changed and lead.phone_e164:
        contact.phone_e164 = lead.phone_e164
    after = {"email": contact.email, "phone_e164": contact.phone_e164}
    if after == before:
        return False
    await audit.record(
        session,
        actor,
        "lead.contact_sync",
        "client",
        lead.client_id,
        before={"contact_id": contact.id, **before},
        after={"contact_id": contact.id, **after},
    )
    await bus_events.contact_updated(session, contact, actor)
    return True
