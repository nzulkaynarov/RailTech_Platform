"""Группы Telegram с секретарём и их беседы (ADR-0032, `services/telegram_groups.py`)."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.clients import Client
from app.models.integrations import TelegramGroup
from app.models.leads import Conversation, Lead, Message

GROUP: str = "group"


async def get(
    session: AsyncSession, chat_id: int, *, for_update: bool = False
) -> TelegramGroup | None:
    return await session.get(TelegramGroup, chat_id, with_for_update=for_update)


async def by_code(session: AsyncSession, code: str) -> TelegramGroup | None:
    stmt = select(TelegramGroup).where(TelegramGroup.connect_code == code).with_for_update()
    found: TelegramGroup | None = (await session.scalars(stmt)).first()
    return found


async def list_all(
    session: AsyncSession, now: datetime, limit: int, offset: int
) -> Sequence[TelegramGroup]:
    """Ждущие живого кода — первыми; затем остальные; ждущие с просроченным кодом — последними."""
    waiting = and_(
        TelegramGroup.status == "pending",
        TelegramGroup.code_expires_at.is_not(None),
        TelegramGroup.code_expires_at > now,
    )
    stale = and_(TelegramGroup.status == "pending", ~waiting)
    stmt = (
        select(TelegramGroup)
        .order_by(
            case((waiting, 0), (stale, 2), else_=1),
            TelegramGroup.updated_at.desc(),
            TelegramGroup.chat_id,
        )
        .limit(limit)
        .offset(offset)
    )
    return (await session.scalars(stmt)).all()


async def client_names(session: AsyncSession, client_ids: Sequence[int]) -> dict[int, str]:
    if not client_ids:
        return {}
    rows = await session.execute(select(Client.id, Client.name).where(Client.id.in_(client_ids)))
    return dict(rows.all())


async def lead_ids(session: AsyncSession, chat_ids: Sequence[int]) -> dict[int, int]:
    """Якорный лид беседы по каждой группе."""
    if not chat_ids:
        return {}
    rows = await session.execute(
        select(Conversation.tg_chat_id, Conversation.lead_id).where(
            Conversation.channel == GROUP, Conversation.tg_chat_id.in_(chat_ids)
        )
    )
    return {chat: lead for chat, lead in rows.all() if chat is not None}


async def conversation_of(
    session: AsyncSession, chat_id: int, *, for_update: bool = False
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.channel == GROUP, Conversation.tg_chat_id == chat_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    found: Conversation | None = (await session.scalars(stmt)).first()
    return found


async def group_lead(session: AsyncSession, client_id: int) -> Lead | None:
    """Якорный лид групп клиента: не обезличенный лид `source = 'group'` (по одному на клиента)."""
    stmt = (
        select(Lead)
        .where(Lead.client_id == client_id, Lead.source == GROUP, Lead.erased_at.is_(None))
        .order_by(Lead.id)
        .limit(1)
        .with_for_update()
    )
    found: Lead | None = (await session.scalars(stmt)).first()
    return found


async def staff_by_telegram(session: AsyncSession, tg_user_id: int) -> User | None:
    stmt = select(User).where(User.tg_user_id == tg_user_id, User.is_active.is_(True))
    found: User | None = (await session.scalars(stmt)).first()
    return found


async def message_by_tg_id(
    session: AsyncSession, conversation_id: int, tg_message_id: int
) -> Message | None:
    stmt = select(Message).where(
        Message.conversation_id == conversation_id, Message.tg_message_id == tg_message_id
    )
    found: Message | None = (await session.scalars(stmt.limit(1).with_for_update())).first()
    return found
