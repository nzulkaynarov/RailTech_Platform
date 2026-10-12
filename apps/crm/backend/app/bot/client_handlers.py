"""Команды клиента и номер телефона (Q-011, Q-020). Логика — в `ClientBotService`.

Роутер подключается раньше `handlers.router`: команды /docs, /request, /status и
контакт не должны попасть в обработчики «неизвестная команда» и «контакт текстом».
"""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.bot import keyboards
from app.bot.handlers import MEDIA, respond, send
from app.domain.bot_menu import normalize_phone
from app.services.client_bot import ClientBotService
from app.services.conversation import ConversationService
from app.services.settings import SettingsService

router = Router(name="client-bot-client")
router.message.filter(F.chat.type == "private")


class RequestForm(StatesGroup):
    summary = State()


class PhoneForm(StatesGroup):
    """Бот показал клавиатуру номера: «Не сейчас» перехватываем только в этом состоянии."""

    pending = State()


def _uid(message: Message) -> int:
    if message.from_user is None:  # отфильтровано F.from_user
        raise ValueError("message without sender")
    return message.from_user.id


async def _not_client(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    cfg = await settings.get()
    status = await client_bot.status(_uid(message))
    await message.answer(cfg.texts.client_only.get(status.language))


@router.message(Command("docs"), F.from_user)
async def on_docs(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    items = await client_bot.documents(_uid(message))
    if items is None:
        await _not_client(message, client_bot, settings)
        return
    cfg = await settings.get()
    language = (await client_bot.status(_uid(message))).language
    if not items:
        await message.answer(cfg.texts.docs_empty.get(language))
        return
    await message.answer(cfg.texts.docs_list.get(language), reply_markup=keyboards.documents(items))


@router.callback_query(F.data.startswith(keyboards.DOC_PREFIX))
async def on_document(
    query: CallbackQuery, bot: Bot, client_bot: ClientBotService, settings: SettingsService
) -> None:
    await query.answer()
    if query.message is None or query.message.chat.type != "private":
        return
    raw = (query.data or "").removeprefix(keyboards.DOC_PREFIX)
    outgoing = await client_bot.document(query.from_user.id, int(raw)) if raw.isdigit() else None
    if outgoing is None:
        cfg = await settings.get()
        language = (await client_bot.status(query.from_user.id)).language
        await bot.send_message(query.message.chat.id, cfg.texts.document_failed.get(language))
        return
    await send(bot, query.message.chat.id, [outgoing], settings)


@router.message(Command("request"), F.from_user)
async def on_request(
    message: Message, client_bot: ClientBotService, settings: SettingsService, state: FSMContext
) -> None:
    status = await client_bot.status(_uid(message))
    if status.client_id is None:
        await _not_client(message, client_bot, settings)
        return
    cfg = await settings.get()
    await state.set_state(RequestForm.summary)
    await message.answer(cfg.texts.request_prompt.get(status.language))


@router.message(RequestForm.summary, F.text, ~F.text.startswith("/"), F.from_user)
async def on_request_summary(
    message: Message, client_bot: ClientBotService, settings: SettingsService, state: FSMContext
) -> None:
    await state.clear()
    text = await client_bot.create_request(_uid(message), (message.text or "").strip())
    if text is None:
        await _not_client(message, client_bot, settings)
        return
    await message.answer(text)


@router.message(Command("status"), F.from_user)
async def on_status(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    text = await client_bot.request_status(_uid(message))
    if text is None:
        await _not_client(message, client_bot, settings)
        return
    await message.answer(text)


@router.message(F.contact, F.from_user)
async def on_contact(
    message: Message, client_bot: ClientBotService, settings: SettingsService, state: FSMContext
) -> None:
    """Сохраняем только собственный номер отправителя (кнопка request_contact), не чужой контакт."""
    if message.contact is None:
        return
    cfg = await settings.get()
    language = (await client_bot.status(_uid(message))).language
    phone = normalize_phone(message.contact.phone_number)
    if message.contact.user_id != _uid(message) or phone is None:
        await message.answer(cfg.texts.phone_not_own.get(language))
        return
    await state.clear()
    await client_bot.save_phone(_uid(message), phone)
    await message.answer(cfg.texts.phone_saved.get(language), reply_markup=ReplyKeyboardRemove())


async def _is_skip(message: Message, settings: SettingsService) -> bool:
    cfg = await settings.get()
    skip = cfg.texts.phone_skip_button
    return message.text in (skip.ru, skip.uz, skip.en)


@router.message(PhoneForm.pending, F.text, F.from_user, _is_skip)
async def on_phone_skip(
    message: Message, client_bot: ClientBotService, settings: SettingsService, state: FSMContext
) -> None:
    """«Не сейчас» — убрать клавиатуру; второй раз номер не спрашиваем (флаг уже стоит)."""
    await state.clear()
    cfg = await settings.get()
    language = (await client_bot.status(_uid(message))).language
    await message.answer(cfg.texts.phone_skipped.get(language), reply_markup=ReplyKeyboardRemove())


@router.message(PhoneForm.pending, F.text, ~F.text.startswith("/"), F.from_user)
async def on_text_instead_of_phone(
    message: Message,
    bot: Bot,
    conversation: ConversationService,
    client_bot: ClientBotService,
    settings: SettingsService,
    state: FSMContext,
) -> None:
    """Человек пишет вместо кнопки: отвечаем как обычно и убираем клавиатуру номера."""
    await state.clear()
    await respond(message, bot, conversation, settings, client_bot, remove_reply_keyboard=True)


@router.message(RequestForm.summary, MEDIA, F.from_user)
async def on_request_media(
    message: Message, client_bot: ClientBotService, settings: SettingsService
) -> None:
    """Описание запроса ждём текстом; ожидание не сбрасываем."""
    cfg = await settings.get()
    language = (await client_bot.status(_uid(message))).language
    await message.answer(cfg.texts.request_text_only.get(language))
