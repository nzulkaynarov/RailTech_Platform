"""Беседа кабинета и каналы переписки (CHAT-1, ADR-0023): запросы без решений.

Беседа `cabinet` — одна на клиента и на компанию ERP (частичные уникальные индексы
`uq_conversations_cabinet_*`); правила выбора якорного лида и ответа — `services/cabinet_chat.py`.
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client
from app.models.leads import Conversation, Lead, Message

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


async def lead_cabinet_company(session: AsyncSession, lead_id: int) -> int | None:
    """Компания ERP беседы кабинета, которую ведёт лид (для `lead.erased`); нет — None."""
    stmt = select(Conversation.erp_company_id).where(
        Conversation.lead_id == lead_id,
        Conversation.channel == CABINET,
        Conversation.erp_company_id.is_not(None),
    )
    value: int | None = (await session.scalars(stmt.limit(1))).first()
    return value


async def anchor_lead(session: AsyncSession, client_id: int) -> Lead | None:
    """Лид клиента с последней активностью (не обезличенный): последнее сообщение клиента, иначе
    последнее изменение лида. Песочница не в счёт."""
    stmt = (
        select(Lead)
        .where(Lead.client_id == client_id, Lead.erased_at.is_(None), Lead.source != "sandbox")
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
