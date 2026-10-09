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
from aiogram.utils.chat_action import ChatActionSender

from app.bot import keyboards
from app.integrations.s3 import ObjectStorage
from app.schemas.settings import Language
from app.services.conversation import ConversationService, Incoming, Outgoing
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
router = Router(name="client-bot")
# Лиды — только личные чаты: сообщения групп, куда добавили бота, не становятся лидами.
router.message.filter(F.chat.type == "private")

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


async def send(
    bot: Bot,
    chat_id: int,
    outgoing: list[Outgoing],
    settings: SettingsService,
    conversation: ConversationService | None = None,
) -> None:
    if not outgoing:
        return
    cfg = await settings.get()
    for item in outgoing:
        if item.document is not None:
            if not await _send_document(bot, chat_id, item):
                # Не пишем «Отправляю документ» без файла; команда узнаёт о сбое.
                await bot.send_message(chat_id, cfg.texts.document_failed.get(item.language))
                if conversation is not None and item.lead_id is not None:
                    await conversation.report_delivery_failure(item.lead_id)
            continue
        markup = None
        if item.keyboard == "consent":
            markup = keyboards.consent(cfg, item.language)
        elif item.keyboard == "language":
            markup = keyboards.languages()
        elif item.keyboard == "erase_confirm":
            markup = keyboards.erase_confirm(cfg, item.language)
        elif item.keyboard == "handoff_offer":
            markup = keyboards.handoff_offer(cfg, item.language)
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
    out = await conversation.erase_prompt(_user(message).id)
    await send(bot, message.chat.id, out, settings)


@router.message(Command("human"), F.from_user)
async def on_human(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    inc = _incoming(message, message.text or "/human", human_requested=True)
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.text.startswith("/"), F.from_user)
async def on_unknown_command(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    """Неизвестная команда — подсказка, а не вопрос модели."""
    await send(bot, message.chat.id, await conversation.help(_user(message).id), settings)


@router.message(F.text, F.from_user)
async def on_text(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    inc = _incoming(message, message.text or "")
    # Ответ модели может идти десятки секунд — показываем «печатает…».
    async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
        out = await conversation.handle_message(inc)
    await send(bot, message.chat.id, out, settings, conversation)


MEDIA = F.document | F.photo | F.voice | F.audio | F.video | F.video_note | F.animation


@router.message(MEDIA, F.from_user)
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


@router.message(F.contact | F.location, F.from_user)
async def on_contact_or_location(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    """Контакт и геопозиция — в переписку текстом: менеджер увидит их в CRM."""
    inc = _incoming(message, _shared_text(message))
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.from_user)
async def on_unsupported(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    """Стикеры, опросы и прочее не теряются молча: просим написать текстом."""
    await send(bot, message.chat.id, await conversation.unsupported(_user(message).id), settings)


@router.callback_query(F.data.in_({keyboards.CONSENT_ACCEPT, keyboards.CONSENT_DECLINE}))
async def on_consent(
    query: CallbackQuery, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await query.answer()
    message = query.message
    if message is None:
        return
    if query.data == keyboards.CONSENT_DECLINE:
        await send(
            bot, message.chat.id, await conversation.decline_consent(query.from_user.id), settings
        )
        return
    if isinstance(message, Message):
        await message.edit_reply_markup(reply_markup=None)
    out = await conversation.accept_consent(query.from_user.id)
    await send(bot, message.chat.id, out, settings)


@router.callback_query(F.data.in_({keyboards.ERASE_CONFIRM, keyboards.ERASE_CANCEL}))
async def on_erase(
    query: CallbackQuery, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await query.answer()
    if query.message is None:
        return
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    user_id = query.from_user.id
    if query.data == keyboards.ERASE_CONFIRM:
        out = await conversation.erase(user_id)
    else:
        out = await conversation.erase_cancelled(user_id)
    await send(bot, query.message.chat.id, out, settings)


@router.callback_query(F.data.in_({keyboards.OFFER_HUMAN, keyboards.OFFER_NO}))
async def on_handoff_offer(
    query: CallbackQuery, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    await query.answer()
    message = query.message
    if not isinstance(message, Message):
        return
    await message.edit_reply_markup(reply_markup=None)
    if query.data != keyboards.OFFER_HUMAN:
        return
    cfg = await settings.get()
    language = await conversation.language_of(query.from_user.id)
    inc = Incoming(
        tg_user_id=query.from_user.id,
        chat_id=message.chat.id,
        text=cfg.texts.handoff_offer_yes.get(language),
        human_requested=True,
    )
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


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


def _shared_text(message: Message) -> str:
    if message.contact is not None:
        contact = message.contact
        name = " ".join(filter(None, (contact.first_name, contact.last_name)))
        return f"📇 {name}: {contact.phone_number}".strip()
    if message.location is not None:
        return f"📍 {message.location.latitude:.5f}, {message.location.longitude:.5f}"
    return ""


def _media(message: Message) -> tuple[str, str, str, int] | None:
    """file_id, имя, mime, размер вложения Telegram любого поддерживаемого вида."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, "photo.jpg", "image/jpeg", photo.file_size or 0
    named = message.document or message.audio or message.video or message.animation
    if named is not None:
        return (
            named.file_id,
            named.file_name or "file",
            named.mime_type or "application/octet-stream",
            named.file_size or 0,
        )
    if message.voice is not None:
        voice = message.voice
        return voice.file_id, "voice.ogg", voice.mime_type or "audio/ogg", voice.file_size or 0
    if message.video_note is not None:
        note = message.video_note
        return note.file_id, "video_note.mp4", "video/mp4", note.file_size or 0
    return None


async def _store_attachment(
    message: Message, bot: Bot, storage: ObjectStorage, bucket: str
) -> dict[str, Any] | None:
    media = _media(message)
    if media is None:
        return None
    file_id, name, mime, size = media
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
