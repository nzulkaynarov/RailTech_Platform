"""Беседа кабинета и каналы переписки (CHAT-1, ADR-0023): запросы без решений.

Беседа `cabinet` — одна на клиента и на компанию ERP (частичные уникальные индексы
`uq_conversations_cabinet_*`); правила выбора якорного лида и ответа — `services/cabinet_chat.py`.
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.reply_channel import ReplyFacts, ReplyVia, reply_via
from app.models.clients import Client, ClientContact
from app.models.inbound_mail import InboundMail
from app.models.leads import Conversation, Lead, Message, TelegramIdentity
from app.repositories.leads import ERASED_TEXT
from app.services import bounces

CABINET: Final = "cabinet"
TELEGRAM: Final = "telegram"


async def client_of(
    session: AsyncSession, crm_client_id: int | None, erp_company_id: int
) -> Client | None:
    """Клиент сообщения: по сопоставлению ERP (`crm_client_id`), иначе по
    `clients.erp_company_id`."""
    if crm_client_id is not None:
        client = await session.get(Client, crm_client_id)
        if client is not None:
            return client
    stmt = select(Client).where(Client.erp_company_id == erp_company_id).order_by(Client.id)
    found: Client | None = (await session.scalars(stmt.limit(1))).first()
    return found


async def cabinet_conversation(
    session: AsyncSession, client_id: int | None, erp_company_id: int
) -> Conversation | None:
    """Беседа кабинета клиента, иначе — беседа компании ERP (заведённая, пока клиента не было)."""
    if client_id is not None:
        stmt = select(Conversation).where(
            Conversation.channel == CABINET, Conversation.client_id == client_id
        )
        found = (await session.scalars(stmt.with_for_update())).first()
        if found is not None:
            return found
    stmt = select(Conversation).where(
        Conversation.channel == CABINET, Conversation.erp_company_id == erp_company_id
    )
    by_company: Conversation | None = (await session.scalars(stmt.with_for_update())).first()
    return by_company


async def cabinet_conversations_of(session: AsyncSession, lead: Lead) -> list[Conversation]:
    """Беседы кабинета, которых касается обезличивание лида: где он якорь и беседа его клиента."""
    match = Conversation.lead_id == lead.id
    if lead.client_id is not None:
        match = match | (Conversation.client_id == lead.client_id)
    stmt = (
        select(Conversation)
        .where(Conversation.channel == CABINET, match)
        .order_by(Conversation.id)
        .with_for_update()
    )
    return list((await session.scalars(stmt)).all())


async def person_contacts(session: AsyncSession, lead_id: int) -> list[int]:
    """Контакты клиента, которые и есть человек лида (его Telegram-идентичность)."""
    identities = select(TelegramIdentity.id).where(TelegramIdentity.lead_id == lead_id)
    stmt = select(ClientContact.id).where(ClientContact.telegram_identity_id.in_(identities))
    return list((await session.scalars(stmt)).all())


async def erase_authors(
    session: AsyncSession, conversation_ids: Sequence[int], crm_contact_ids: Sequence[int]
) -> list[int]:
    """Сообщения кабинета этих контактов CRM: текст стёрт, автора нет («Удалённый пользователь»).
    Возвращает контакты ERP — авторов стёртых сообщений (для ERP)."""
    if not conversation_ids or not crm_contact_ids:
        return []
    stmt = select(Message).where(
        Message.conversation_id.in_(conversation_ids),
        Message.role == "lead",
        Message.meta["crm_contact_id"].astext.in_([str(c) for c in crm_contact_ids]),
    )
    erp_contacts: set[int] = set()
    for message in (await session.scalars(stmt)).all():
        meta = dict(message.meta or {})
        if isinstance(meta.get("erp_contact_id"), int):
            erp_contacts.add(meta["erp_contact_id"])
        message.text = ERASED_TEXT
        message.attachments = []
        message.meta = {
            "channel": CABINET,
            "erased": True,
            **(
                {"client_message_id": meta["client_message_id"]}
                if "client_message_id" in meta
                else {}
            ),
        }
    return sorted(erp_contacts)


async def anchor_lead(
    session: AsyncSession, client_id: int, *, exclude: int | None = None
) -> Lead | None:
    """Лид клиента с последней активностью (не обезличенный): последнее сообщение клиента, иначе
    последнее изменение лида. Песочница не в счёт."""
    stmt = (
        select(Lead)
        .where(
            Lead.client_id == client_id,
            Lead.erased_at.is_(None),
            Lead.source != "sandbox",
            Lead.id != (exclude or 0),
        )
        .order_by(
            Lead.last_lead_msg_at.desc().nulls_last(),
            Lead.updated_at.desc(),
            Lead.id.desc(),
        )
        .limit(1)
        .with_for_update()
    )
    found: Lead | None = (await session.scalars(stmt)).first()
    return found


async def waits_for_reply(session: AsyncSession, conversation_id: int) -> bool:
    """Беседа кабинета ждёт ответа: последнее сообщение клиента позже последнего ответа менеджера
    в эту же беседу. Считается по самой беседе, а не по отметкам лида: у лида они общие для всех
    его бесед и переписки в Telegram (ответ менеджера своему лиду в Telegram кабинету не ответ)."""
    row = (
        await session.execute(
            select(
                func.max(Message.id).filter(Message.role == "lead"),
                func.max(Message.id).filter(Message.role == "manager"),
            ).where(Message.conversation_id == conversation_id)
        )
    ).one()
    last_in, last_reply = row
    return last_in is not None and (last_reply is None or last_in > last_reply)


async def inbound_by_key(
    session: AsyncSession, conversation_id: int, client_message_id: str
) -> Message | None:
    """Входящее сообщение кабинета с этим ключом повтора (повторная публикация того же
    сообщения)."""
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.role == "lead",
        Message.meta["client_message_id"].astext == client_message_id,
    )
    found: Message | None = (await session.scalars(stmt.limit(1))).first()
    return found


async def last_inbound_channels(session: AsyncSession, lead_ids: Sequence[int]) -> dict[int, str]:
    """Канал последнего сообщения клиента по каждому лиду — туда уйдёт ответ менеджера."""
    if not lead_ids:
        return {}
    latest = (
        select(func.max(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id.in_(set(lead_ids)), Message.role == "lead")
        .group_by(Conversation.lead_id)
    )
    stmt = (
        select(Conversation.lead_id, Conversation.channel)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(Message.id.in_(latest))
    )
    return {row.lead_id: row.channel for row in (await session.execute(stmt)).all()}


async def last_inbound_channel(session: AsyncSession, lead_id: int) -> str | None:
    return (await last_inbound_channels(session, [lead_id])).get(lead_id)


async def open_cabinet_conversation(session: AsyncSession, lead_id: int) -> Conversation | None:
    stmt = (
        select(Conversation)
        .where(
            Conversation.lead_id == lead_id,
            Conversation.channel == CABINET,
            Conversation.is_open,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    found: Conversation | None = (await session.scalars(stmt)).first()
    return found


async def reply_vias(session: AsyncSession, leads: Sequence[Lead]) -> dict[int, ReplyVia]:
    """Канал ответа менеджера по каждому лиду (CH-1, `domain/reply_channel.py`): факты одним пакетом
    запросов — открытые беседы, телефон, канал последнего входящего."""
    if not leads:
        return {}
    ids = [lead.id for lead in leads]
    rows = (
        await session.execute(
            select(Conversation.lead_id, Conversation.channel, Conversation.tg_chat_id)
            .where(Conversation.lead_id.in_(ids), Conversation.is_open)
            .add_columns(Conversation.erp_company_id)
        )
    ).all()
    telegram = {r.lead_id for r in rows if r.channel == TELEGRAM and r.tg_chat_id is not None}
    cabinet = {r.lead_id for r in rows if r.channel == CABINET and r.erp_company_id is not None}
    with_phone = set(
        (
            await session.scalars(
                select(TelegramIdentity.lead_id).where(
                    TelegramIdentity.lead_id.in_(ids), TelegramIdentity.phone_e164.is_not(None)
                )
            )
        ).all()
    )
    client_ids = {lead.client_id for lead in leads if lead.client_id is not None}
    clients_with_phone = set(
        (
            await session.scalars(
                select(ClientContact.client_id).where(
                    ClientContact.client_id.in_(client_ids),
                    ClientContact.is_primary.is_(True),
                    ClientContact.phone_e164.is_not(None),
                )
            )
        ).all()
        if client_ids
        else []
    )
    last = await last_inbound_channels(session, ids)
    mailed = set(
        (
            await session.scalars(select(InboundMail.lead_id).where(InboundMail.lead_id.in_(ids)))
        ).all()
    ) | set(
        (
            await session.scalars(
                select(InboundMail.matched_lead_id).where(InboundMail.matched_lead_id.in_(ids))
            )
        ).all()
    )
    blocked = await bounces.states(session, [lead.email for lead in leads])
    return {
        lead.id: reply_via(
            ReplyFacts(
                has_telegram=lead.id in telegram,
                has_cabinet=lead.id in cabinet,
                has_consent=lead.consent_given_at is not None,
                email=lead.email,
                has_phone=bool(lead.phone_e164)
                or lead.id in with_phone
                or lead.client_id in clients_with_phone,
                source=lead.source,
                last_inbound=last.get(lead.id),
                inbound_mail=lead.id in mailed,
                email_blocked=(lead.email or "").strip().lower() in blocked,
            )
        )
        for lead in leads
    }


async def bot_channel_leads(session: AsyncSession, lead_ids: Sequence[int]) -> set[int]:
    """Лиды с чатом Telegram (в любом состоянии): только им можно «Вернуть боту»."""
    if not lead_ids:
        return set()
    stmt = select(Conversation.lead_id).where(
        Conversation.lead_id.in_(set(lead_ids)),
        Conversation.channel == TELEGRAM,
        Conversation.tg_chat_id.is_not(None),
    )
    return set((await session.scalars(stmt)).all())
