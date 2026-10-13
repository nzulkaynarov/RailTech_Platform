"""Кандидаты в канал команды, найденные по `my_chat_member` (`app/bot/chat_member.py`)."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrations import TelegramChatCandidate


async def upsert(session: AsyncSession, chat_id: int, title: str, chat_type: str) -> None:
    stmt = insert(TelegramChatCandidate).values(
        chat_id=chat_id, title=title[:255], chat_type=chat_type
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[TelegramChatCandidate.chat_id],
            set_={
                "title": stmt.excluded.title,
                "chat_type": stmt.excluded.chat_type,
                "detected_at": stmt.excluded.detected_at,
            },
        )
    )


async def remove(session: AsyncSession, chat_id: int) -> None:
    await session.execute(
        delete(TelegramChatCandidate).where(TelegramChatCandidate.chat_id == chat_id)
    )


async def list_all(session: AsyncSession) -> Sequence[TelegramChatCandidate]:
    stmt = select(TelegramChatCandidate).order_by(TelegramChatCandidate.detected_at.desc())
    return (await session.execute(stmt)).scalars().all()


async def get(session: AsyncSession, chat_id: int) -> TelegramChatCandidate | None:
    return await session.get(TelegramChatCandidate, chat_id)
