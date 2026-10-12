"""Обработчики клиентского бота (SPEC §9.2). Логика — в ConversationService.

Зависимости (`conversation`, `settings`, `object_storage`, `attachments_bucket`)
передаются через workflow data диспетчера (`app/bot/runtime.py`).
"""

from typing import Any

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    User,
)
from aiogram.utils.chat_action import ChatActionSender

from app.bot import keyboards
from app.bot.attachments import (
    BEFORE_CONSENT,
    MAX_ATTACHMENT_BYTES,
    attachment_meta,
    media_of,
    shared_text,
    store_attachment,
)
from app.bot.phone_gate import ask_phone_first, human_words_wait_for_phone
from app.domain.bot_menu import MenuVariant, contact_request
from app.domain.language import requested_language
from app.integrations.s3 import ObjectStorage
from app.schemas.settings import AppSettings, Language
from app.services.client_bot import ClientBotService
from app.services.conversation import ConversationService, Incoming, Outgoing
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
router = Router(name="client-bot")
# Лиды — только личные чаты: сообщения групп, куда добавили бота, не становятся лидами.
router.message.filter(F.chat.type == "private")

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
    *,
    remove_reply_keyboard: bool = False,
) -> None:
    """Отправка ответов; `remove_reply_keyboard` — убрать «Поделиться номером» первым ответом."""
    if not outgoing:
        return
    cfg = await settings.get()
    for index, item in enumerate(outgoing):
        if item.document is not None:
            if not await _send_document(bot, chat_id, item):
                # Не пишем «Отправляю документ» без файла; команда узнаёт о сбое.
                await bot.send_message(chat_id, cfg.texts.document_failed.get(item.language))
                if conversation is not None and item.lead_id is not None:
                    await conversation.report_delivery_failure(item.lead_id)
            continue
        markup: InlineKeyboardMarkup | ReplyKeyboardRemove | None = _markup(cfg, item)
        if markup is None and remove_reply_keyboard and index == 0:
            markup = ReplyKeyboardRemove()
        await bot.send_message(chat_id, item.text, reply_markup=markup)


def _markup(cfg: AppSettings, item: Outgoing) -> InlineKeyboardMarkup | None:
    if item.keyboard == "consent":
        return keyboards.consent(cfg, item.language)
    if item.keyboard == "language":
        return keyboards.languages()
    if item.keyboard == "erase_confirm":
        return keyboards.erase_confirm(cfg, item.language)
    if item.keyboard == "handoff_offer":
        return keyboards.handoff_offer(cfg, item.language)
    return None


@router.message(CommandStart(), F.from_user)
async def on_start(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    out = await conversation.start(_incoming(message, "/start"))
    await send(bot, message.chat.id, out, settings)


def help_text(cfg: AppSettings, variant: MenuVariant, language: Language) -> str:
    """/help перечисляет ровно команды меню этого статуса (SPEC §9.2)."""
    texts = cfg.texts
    text = {"prospect": texts.help, "with_manager": texts.help_with_manager}.get(
        variant, texts.help_client
    )
    return text.get(language, company=cfg.company.name)


@router.message(Command("help"), F.from_user)
async def on_help(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    cfg = await settings.get()
    status = await client_bot.status(_user(message).id)
    await message.answer(help_text(cfg, status.variant, status.language))


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
    message: Message,
    bot: Bot,
    conversation: ConversationService,
    settings: SettingsService,
    client_bot: ClientBotService,
    state: FSMContext | None = None,
) -> None:
    inc = _incoming(message, message.text or "/human", human_requested=True)
    if await ask_phone_first(inc, bot, conversation, client_bot, settings, state):
        return
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.text.startswith("/"), F.from_user)
async def on_unknown_command(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    """Неизвестная команда — подсказка, а не вопрос модели."""
    await on_help(message, client_bot, settings)


@router.message(F.text, F.from_user)
async def on_text(
    message: Message,
    bot: Bot,
    conversation: ConversationService,
    settings: SettingsService,
    client_bot: ClientBotService,
    state: FSMContext | None = None,
) -> None:
    await respond(message, bot, conversation, settings, client_bot, state)


async def respond(
    message: Message,
    bot: Bot,
    conversation: ConversationService,
    settings: SettingsService,
    client_bot: ClientBotService,
    state: FSMContext | None = None,
    *,
    remove_reply_keyboard: bool = False,
) -> None:
    """Текст лида: смена языка и контакты компании решает код, остальное — диалог."""
    text, uid, chat_id = message.text or "", _user(message).id, message.chat.id
    out = await _deterministic(message, text, uid, conversation, settings)
    if out is None and await human_words_wait_for_phone(
        _incoming(message, text, human_requested=True),
        bot,
        conversation,
        client_bot,
        settings,
        state,
    ):
        return
    if out is None:
        # Ответ модели может идти десятки секунд — показываем «печатает…».
        async with ChatActionSender.typing(chat_id=chat_id, bot=bot):
            out = await conversation.handle_message(_incoming(message, text))
        offer = await client_bot.language_offer(uid, text)
        if offer is not None:
            cfg = await settings.get()
            out.append(Outgoing(cfg.texts.language_prompt.get(offer), keyboard="language"))
    await send(
        bot, chat_id, out, settings, conversation, remove_reply_keyboard=remove_reply_keyboard
    )


async def _deterministic(
    message: Message,
    text: str,
    uid: int,
    conversation: ConversationService,
    settings: SettingsService,
) -> list[Outgoing] | None:
    """Ответ без модели (Q-022, Q-023): «давай по-русски» и «дайте телефон/адрес/сайт».

    Сообщение лида и ответ пишутся в переписку — менеджер видит их в CRM.
    """
    language = requested_language(text)
    cfg = await settings.get()
    if language is None and not contact_request(text, cfg.escalation.human_request_terms):
        return None
    await conversation.record_lead_message(_incoming(message, text))
    if language is not None:
        return await conversation.set_language(uid, language)  # подтверждение пишет сервис
    current = await conversation.language_of(uid)
    contacts = cfg.company_contacts(current)
    if contacts is not None:
        out = [Outgoing(contacts, language=current)]
    else:
        missing = cfg.texts.contacts_missing.get(current)
        out = [Outgoing(missing, keyboard="handoff_offer", language=current)]
    await conversation.record_bot_replies(uid, out)
    return out


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
    uid = _user(message).id
    media = media_of(message)
    if media is not None and media[3] > MAX_ATTACHMENT_BYTES:
        # Больше 20 МБ Telegram боту не отдаёт: честно просим ссылку, без «получил, передам».
        meta = attachment_meta(media) | {"stored": False, "too_large": True}
        await conversation.record_lead_message(
            _incoming(message, message.caption or "", attachments=[meta])
        )
        cfg = await settings.get()
        out = [Outgoing(cfg.texts.attachment_too_large.get(await conversation.language_of(uid)))]
        await conversation.record_bot_replies(uid, out)
        await send(bot, message.chat.id, out, settings)
        return
    if await conversation.accepts_files(uid):
        attachment = await store_attachment(message, bot, object_storage, attachments_bucket)
    else:
        # До согласия файл не загружается в хранилище — в переписке остаётся пометка.
        attachment = attachment_meta(media) | BEFORE_CONSENT if media else None
    inc = _incoming(message, message.caption or "", attachments=[attachment] if attachment else [])
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.contact | F.location, F.from_user)
async def on_contact_or_location(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    """Контакт и геопозиция — в переписку текстом: менеджер увидит их в CRM."""
    inc = _incoming(message, shared_text(message))
    await send(bot, message.chat.id, await conversation.handle_message(inc), settings)


@router.message(F.from_user)
async def on_unsupported(
    message: Message, bot: Bot, conversation: ConversationService, settings: SettingsService
) -> None:
    """Стикеры, опросы и прочее не теряются молча: просим написать текстом."""
    out = await conversation.unsupported(_user(message).id)
    await conversation.record_bot_replies(_user(message).id, out)
    await send(bot, message.chat.id, out, settings)


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
    query: CallbackQuery,
    bot: Bot,
    conversation: ConversationService,
    settings: SettingsService,
    client_bot: ClientBotService,
    state: FSMContext | None = None,
) -> None:
    await query.answer()
    message = query.message
    if not isinstance(message, Message):
        return
    await message.edit_reply_markup(reply_markup=None)
    cfg = await settings.get()
    language = await conversation.language_of(query.from_user.id)
    if query.data != keyboards.OFFER_HUMAN:
        out = [Outgoing(cfg.texts.handoff_offer_declined.get(language), language=language)]
        await conversation.record_bot_replies(query.from_user.id, out)
        await send(bot, message.chat.id, out, settings)
        return
    inc = Incoming(
        tg_user_id=query.from_user.id,
        chat_id=message.chat.id,
        text=cfg.texts.handoff_offer_yes.get(language),
        human_requested=True,
    )
    if await ask_phone_first(inc, bot, conversation, client_bot, settings, state):
        return
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
