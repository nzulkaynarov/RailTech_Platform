"""Секретарь в группах клиентов (ADR-0032): запись сообщений привязанной группы в карточку клиента.

Бот в группе не отвечает: ни диалога с ИИ, ни сценария лида личного чата — только запись. Группа,
которая не привязана (ждёт код, отключена), не записывается вовсе. Свои сообщения бот и сообщения
других ботов не пишет. Удаление сообщения боту не приходит (Bot API его не присылает), поэтому в
системе сообщение остаётся.
"""

from typing import Any

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.attachments import attachment_meta, media_of, store_attachment
from app.domain import telegram_groups as rules
from app.integrations.s3 import ObjectStorage
from app.services.telegram_groups import GroupMessage, TelegramGroupService

logger = structlog.get_logger(__name__)
router = Router(name="client-groups")
router.message.filter(F.chat.type.in_(rules.GROUP_CHAT_TYPES))
router.edited_message.filter(F.chat.type.in_(rules.GROUP_CHAT_TYPES))

MAX_TEXT_CHARS = 4000
# Сообщения от имени группы или канала приходят от этого служебного пользователя.
ANONYMOUS_ADMIN_ID = 1087968824


def _author(message: Message, bot_id: int) -> tuple[int | None, str, str | None] | None:
    """(id, имя, ник) автора; None — писать не надо: сам бот или чужой бот."""
    sender = message.from_user
    if message.sender_chat is not None:  # от имени группы или канала (анонимный админ)
        return None, message.sender_chat.title or "", message.sender_chat.username
    if sender is None or sender.id == bot_id:
        return None
    if sender.is_bot and sender.id != ANONYMOUS_ADMIN_ID:
        return None
    return sender.id, sender.full_name, sender.username


async def _attachments(
    message: Message, bot: Bot, storage: ObjectStorage, bucket: str
) -> list[dict[str, Any]]:
    media = media_of(message)
    if media is None:
        return []
    try:
        stored = await store_attachment(message, bot, storage, bucket)
    except Exception as exc:  # noqa: BLE001 — Telegram или хранилище: сообщение не теряем
        logger.warning("group_file_store_failed", chat_id=message.chat.id, error=type(exc).__name__)
        stored = None
    meta = stored or attachment_meta(media) | {"stored": False}
    if meta.get("too_large"):
        meta = {**meta, "note": rules.NOTE_TOO_LARGE}
    elif not meta.get("stored"):
        meta = {**meta, "note": rules.NOTE_NOT_STORED}
    return [meta]


@router.message(Command("connect"))
async def on_connect(
    message: Message, bot: Bot, groups: TelegramGroupService | None = None
) -> None:
    """Новый код привязки — по просьбе администратора группы (прежний просрочен или потерян)."""
    sender = message.from_user
    if groups is None or sender is None:
        return
    try:
        member = await bot.get_chat_member(message.chat.id, sender.id)
    except TelegramAPIError:
        return
    if member.status not in {"administrator", "creator"}:
        return
    code = await groups.issue_code(message.chat.id)
    if code is None:
        return
    language = await groups.language_of(message.chat.id)
    await message.answer(rules.text(rules.CODE_MESSAGE, language, code=code))


@router.message()
async def on_group_message(
    message: Message,
    bot: Bot,
    groups: TelegramGroupService | None = None,
    object_storage: ObjectStorage | None = None,
    attachments_bucket: str = "",
) -> None:
    author = _author(message, bot.id)
    if groups is None or author is None:
        return
    # Не привязана — ничего не качаем и не пишем (запись группы уже есть, больше ничего нет).
    if not await groups.is_bound(message.chat.id):
        return
    text = (message.text or message.caption or "")[:MAX_TEXT_CHARS]
    attachments = (
        await _attachments(message, bot, object_storage, attachments_bucket)
        if object_storage is not None
        else []
    )
    if not text and not attachments:
        return  # служебное сообщение (вошёл, вышел, закреп): записывать нечего
    sender_id, name, username = author
    await groups.capture(
        GroupMessage(
            chat_id=message.chat.id,
            message_id=message.message_id,
            sender_id=sender_id,
            sender_name=name,
            sender_username=username,
            text=text,
            reply_to_message_id=message.reply_to_message.message_id
            if message.reply_to_message
            else None,
            attachments=attachments,
        )
    )


@router.edited_message()
async def on_group_edit(
    message: Message, bot: Bot, groups: TelegramGroupService | None = None
) -> None:
    if groups is None or _author(message, bot.id) is None:
        return
    await groups.edit(
        message.chat.id,
        message.message_id,
        (message.text or message.caption or "")[:MAX_TEXT_CHARS],
    )
