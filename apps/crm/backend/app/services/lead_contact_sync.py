"""Почта и телефон, добавленные в карточке лида, доходят до контакта компании (КОНТР-1а).

Контакт выбирается только по собственным признакам этого человека: контакт из метки беседы
(`known_contact.contact_id` — тот, по которому беседа опознана), иначе контакт, связанный с
Telegram этого лида. Основной и единственный контакты не подставляются: так почта одного человека
не попадёт в карточку другого и не откроет ему чужой кабинет. Пишется только в пустое поле;
другое значение не перезаписывается — на карточке лида остаётся заметка «измените в карточке
контакта».
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.company_conversation import MARK_KEY
from app.models.clients import ClientContact
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.security import audit
from app.security.audit import Actor

CONFLICT_NOTE = (
    "У контакта компании уже указан другой адрес или телефон — измените в карточке контакта."
)


async def own_contact(session: AsyncSession, lead: Lead) -> ClientContact | None:
    """Контакт компании, который этот лид однозначно представляет; иначе `None`."""
    if lead.client_id is None:
        return None
    marked = ((lead.qualification or {}).get(MARK_KEY) or {}).get("contact_id")
    if isinstance(marked, int):
        contact = await session.get(ClientContact, marked)
        if contact is not None and contact.client_id == lead.client_id:
            return contact
    identities = (
        await session.scalars(
            select(TelegramIdentity.id).where(TelegramIdentity.lead_id == lead.id)
        )
    ).all()
    if not identities:
        return None
    linked = (
        await session.scalars(
            select(ClientContact).where(
                ClientContact.client_id == lead.client_id,
                ClientContact.telegram_identity_id.in_(list(identities)),
            )
        )
    ).all()
    return linked[0] if len(linked) == 1 else None


async def sync_to_contact(
    session: AsyncSession, lead: Lead, changed: Collection[str], actor: Actor
) -> bool:
    """Переносит добавленные почту и телефон лида в пустые поля его контакта; `True` — записано."""
    if lead.client_id is None or not ({"email", "phone"} & set(changed)):
        return False
    contact = await own_contact(session, lead)
    if contact is None:
        return False
    before = {"email": contact.email, "phone_e164": contact.phone_e164}
    conflict = False
    for name, attr, value in (
        ("email", "email", lead.email),
        ("phone", "phone_e164", lead.phone_e164),
    ):
        if name not in changed or not value:
            continue
        current = getattr(contact, attr)
        if not current:
            setattr(contact, attr, value)
        elif current.lower() != value.lower():
            conflict = True
    if conflict:
        session.add(LeadNote(lead_id=lead.id, user_id=actor.user_id, text=CONFLICT_NOTE))
        lead.notes_count += 1
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
