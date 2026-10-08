"""Обработчики клиентского бота (SPEC §9.2). Логика — в ConversationService.

Зависимости (`conversation`, `settings`, `object_storage`, `attachments_bucket`)
передаются через workflow data диспетчера (`app/bot/runtime.py`).
"""

import io
from typing import Any

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message, User

from app.bot import keyboards
from app.integrations.s3 import ObjectStorage
from app.schemas.settings import Language
from app.services.conversation import ConversationService, Incoming, Outgoing
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
router = Router(name="client-bot")

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 4000
LANGUAGES: dict[str, Language] = {"ru": "ru", "uz": "uz", "en": "en"}


def _user(message: Message) -> User:
    if message.from_user is None:  # отфильтровано F.from_user, проверка для типов
        raise ValueError("message without sender")
    return message.from_user


def _incoming(message: Message, text: str, **extra: Any) -> Incoming:
    user = _user(message)
    return Incoming(
        tg_user_id=user.id,
        chat_id=message.chat.id,
        text=text[:MAX_TEXT_CHARS],
        username=user.username,
        first_name=user.first_name,
        language_code=(user.language_code or "")[:2] or None,
        message_id=message.message_id,
        **extra,
    )


async def send(bot: Bot, chat_id: int, outgoing: list[Outgoing], settings: SettingsService) -> None:
    if not outgoing:
        return
    cfg = await settings.get()
    for item in outgoing:
        if item.document is not None and await _send_document(bot, chat_id, item):
            continue
        markup = None
        if item.keyboard == "consent":
            markup = keyboards.consent(cfg, item.language)
        elif item.keyboard == "language":
            markup = keyboards.languages()
        await bot.send_message(chat_id, item.text, reply_markup=markup)


@router.message(CommandStart(), F.from_user)
async def on_start(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    out = await conversation.start(_incoming(message, "/start"))
    await send(bot, message.chat.id, out, settings)


@router.message(Command("help"), F.from_user)
async def on_help(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await send(bot, message.chat.id, await conversation.help(_user(message).id), settings)


@router.message(Command("lang"), F.from_user)
async def on_lang(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    out = await conversation.language_prompt(_user(message).id)
    await send(bot, message.chat.id, out, settings)


@router.message(Command("delete"), F.from_user)
async def on_delete(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await send(bot, message.chat.id, await conversation.erase(_user(message).id), settings)


@router.message(Command("human"), F.from_user)
async def on_human(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    inc = _incoming(message, message.text or "/human", human_requested=True)
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.text, F.from_user)
async def on_text(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    inc = _incoming(message, message.text or "")
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.document | F.photo, F.from_user)
async def on_attachment(
    message: Message,
    bot: Bot,
    conversation: ConversationService,
    settings: SettingsService,
    object_storage: ObjectStorage,
    attachments_bucket: str,
) -> None:
    attachment = await _store_attachment(message, bot, object_storage, attachments_bucket)
    inc = _incoming(message, message.caption or "", attachments=[attachment] if attachment else [])
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.callback_query(F.data == keyboards.CONSENT_ACCEPT)
async def on_consent(
    query: CallbackQuery, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await query.answer()
    if query.message is not None:
        out = await conversation.accept_consent(query.from_user.id)
        await send(bot, query.message.chat.id, out, settings)


@router.callback_query(F.data.startswith(keyboards.LANGUAGE_PREFIX))
async def on_language(
    query: CallbackQuery, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await query.answer()
    language = LANGUAGES.get((query.data or "").removeprefix(keyboards.LANGUAGE_PREFIX))
    if language is not None and query.message is not None:
        out = await conversation.set_language(query.from_user.id, language)
        await send(bot, query.message.chat.id, out, settings)


async def _send_document(bot: Bot, chat_id: int, item: Outgoing) -> bool:
    """Файл документа клиента по ссылке docs-mcp (внутренняя сеть, TTL 10 мин)."""
    doc = item.document or {}
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.get(str(doc["url"]))
            response.raise_for_status()
        file = BufferedInputFile(response.content, filename=str(doc.get("filename") or "document"))
        await bot.send_document(chat_id, file, caption=item.text[:1000])
    except Exception:
        logger.exception("document_send_failed", document_id=doc.get("document_id"))
        return False
    return True


async def _store_attachment(
    message: Message, bot: Bot, storage: ObjectStorage, bucket: str
) -> dict[str, Any] | None:
    if message.document is not None:
        doc = message.document
        file_id, name = doc.file_id, doc.file_name or "document"
        mime, size = doc.mime_type or "application/octet-stream", doc.file_size or 0
    elif message.photo:
        photo = message.photo[-1]
        file_id, name, mime, size = photo.file_id, "photo.jpg", "image/jpeg", photo.file_size or 0
    else:
        return None
    meta: dict[str, Any] = {"kind": "file", "name": name, "mime": mime, "size": size}
    if size > MAX_ATTACHMENT_BYTES:
        return {**meta, "stored": False}
    buffer = io.BytesIO()
    await bot.download(file_id, destination=buffer)
    safe = name.replace("/", "_").replace("\\", "_")[-120:]
    key = f"tg/{message.chat.id}/{message.message_id}/{safe}"
    await storage.put(bucket, key, buffer.getvalue(), mime)
    logger.info("tg_attachment_stored", chat_id=message.chat.id, size=size)
    return {**meta, "storage_key": key, "stored": True}
