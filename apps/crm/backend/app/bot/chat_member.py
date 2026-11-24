"""Авто-обнаружение канала команды (аудит 2026-10-12 §3): бота сделали админом канала/группы.

Бот в чат ничего не пишет: кандидат лишь появляется в «Подключениях», где админ CRM
нажимает «Подключить». Сняли с админов или удалили — кандидат исчезает.
"""

import structlog
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import telegram_groups as group_rules
from app.repositories import telegram_chats
from app.services.telegram_groups import TelegramGroupService

logger = structlog.get_logger(__name__)
router = Router(name="chat-member")

TEAM_CHAT_TYPES = frozenset({"channel", "supergroup", "group"})


def is_admin_now(update: ChatMemberUpdated) -> bool:
    return update.new_chat_member.status in {"administrator", "creator"}


@router.my_chat_member()
async def on_my_chat_member(
    update: ChatMemberUpdated,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    groups: TelegramGroupService | None = None,
) -> None:
    chat = update.chat
    if chat.type not in TEAM_CHAT_TYPES:
        return
    if groups is not None:
        await _client_group(update, bot, groups)
    async with sessions() as session, session.begin():
        if is_admin_now(update):
            title = chat.title or str(chat.id)
            await telegram_chats.upsert(session, chat.id, title, chat.type)
            logger.info("team_chat_detected", chat_id=chat.id, chat_type=chat.type)
        else:
            await telegram_chats.remove(session, chat.id)
            logger.info("team_chat_lost", chat_id=chat.id, status=update.new_chat_member.status)


def _can_pin(update: ChatMemberUpdated) -> bool:
    member = update.new_chat_member
    if member.status == "creator":
        return True
    return bool(getattr(member, "can_pin_messages", False))


async def _client_group(update: ChatMemberUpdated, bot: Bot, groups: TelegramGroupService) -> None:
    """Группа с секретарём (ADR-0032): запись группы и код привязки; канал команды не трогаем."""
    chat = update.chat
    code = await groups.bot_membership(
        chat.id,
        chat.title or str(chat.id),
        chat.type,
        status=update.new_chat_member.status,
        can_pin=_can_pin(update),
    )
    if code is None:
        return
    language = await groups.language_of(chat.id)
    try:
        await bot.send_message(
            chat.id, group_rules.text(group_rules.CODE_MESSAGE, language, code=code)
        )
    except TelegramAPIError as exc:
        logger.warning("group_code_post_failed", chat_id=chat.id, error=type(exc).__name__)
