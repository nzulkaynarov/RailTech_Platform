"""Группы Telegram с секретарём и их беседы (ADR-0032, `services/telegram_groups.py`)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
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


async def list_all(session: AsyncSession) -> Sequence[TelegramGroup]:
    stmt = select(TelegramGroup).order_by(
        (TelegramGroup.status == "pending").desc(), TelegramGroup.updated_at.desc()
    )
    return (await session.scalars(stmt)).all()


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
