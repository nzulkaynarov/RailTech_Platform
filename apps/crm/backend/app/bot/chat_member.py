"""Авто-обнаружение канала команды (аудит 2026-10-12 §3): бота сделали админом канала/группы.

Бот в чат ничего не пишет: кандидат лишь появляется в «Подключениях», где админ CRM
нажимает «Подключить». Сняли с админов или удалили — кандидат исчезает.
"""

import structlog
from aiogram import Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import telegram_chats

logger = structlog.get_logger(__name__)
router = Router(name="chat-member")

TEAM_CHAT_TYPES = frozenset({"channel", "supergroup", "group"})


def is_admin_now(update: ChatMemberUpdated) -> bool:
    return update.new_chat_member.status in {"administrator", "creator"}


@router.my_chat_member()
async def on_my_chat_member(
    update: ChatMemberUpdated, sessions: async_sessionmaker[AsyncSession]
) -> None:
    chat = update.chat
    if chat.type not in TEAM_CHAT_TYPES:
        return
    async with sessions() as session, session.begin():
        if is_admin_now(update):
            title = chat.title or str(chat.id)
            await telegram_chats.upsert(session, chat.id, title, chat.type)
            logger.info("team_chat_detected", chat_id=chat.id, chat_type=chat.type)
        else:
            await telegram_chats.remove(session, chat.id)
            logger.info("team_chat_lost", chat_id=chat.id, status=update.new_chat_member.status)
