"""Меню по статусу, команды клиента и номер телефона (Q-011, Q-020) на подставном Bot."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import (
    BotCommandScopeChat,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.bot import client_handlers
from app.bot.commands import ChatMenus, commands_for
from app.bot.status import ClientStatusMiddleware
from app.schemas.settings import AppSettings
from app.services.client_bot import ChatStatus

CFG = AppSettings()
USER = 42


class FakeSettings:
    async def get(self) -> AppSettings:
        return CFG


@dataclass
class FakeClientBot:
    """Статус задаёт тест; «спросили номер» — один раз, как флаг в лиде."""

    variant: str = "prospect"
    client_id: int | None = None
    phone_due: bool = False
    asked: int = 0
    phones: list[str] = field(default_factory=list)
    docs: list[tuple[int, str]] = field(default_factory=list)

    async def status(self, tg_user_id: int) -> ChatStatus:
        ask = self.phone_due and self.asked == 0
        return ChatStatus(self.variant, "ru", 1, self.client_id, ask)  # type: ignore[arg-type]

    async def mark_phone_asked(self, tg_user_id: int) -> None:
        self.asked += 1

    async def save_phone(self, tg_user_id: int, phone: str) -> None:
        self.phones.append(phone)

    async def documents(self, tg_user_id: int) -> list[tuple[int, str]] | None:
        return self.docs if self.client_id is not None else None


def fake_bot() -> AsyncMock:
    return AsyncMock()


def message(bot: AsyncMock, chat_type: str = "private", **content: Any) -> Message:
    msg = Message.model_validate(
        {
            "message_id": 7,
            "date": datetime(2026, 10, 12, tzinfo=UTC),
            "chat": {"id": USER, "type": chat_type},
            "from": {"id": USER, "is_bot": False, "first_name": "Азиз"},
            **content,
        }
    )
    return msg.as_(bot)


def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=USER, user_id=USER))


def sent(bot: AsyncMock) -> list[SendMessage]:
    """Ответы через `message.answer(...)` — это вызов `bot(SendMessage)`."""
    return [c.args[0] for c in bot.call_args_list if isinstance(c.args[0], SendMessage)]


@pytest.mark.parametrize(
    ("variant", "language", "present", "absent"),
    [
        ("prospect", "ru", "Связаться с менеджером", "Мои документы"),
        ("with_manager", "ru", "Удалить переписку", "Связаться с менеджером"),
        ("client", "ru", "Мои документы", "Начать"),
        ("client", "uz", "Hujjatlarim", "Boshlash"),
        ("client", "en", "Talk to a manager", "Start"),
    ],
)
def test_menu_labels_come_from_settings(
    variant: str, language: str, present: str, absent: str
) -> None:
    labels = [c.description for c in commands_for(CFG, variant, language)]  # type: ignore[arg-type]
    assert present in labels
    assert absent not in labels


async def test_chat_menu_is_published_only_when_status_changes() -> None:
    bot, menus = fake_bot(), ChatMenus()
    assert await menus.ensure(bot, USER, "prospect", "ru", CFG)
    assert not await menus.ensure(bot, USER, "prospect", "ru", CFG)  # без спама API
    assert await menus.ensure(bot, USER, "with_manager", "ru", CFG)  # менеджер взял лида
    assert await menus.ensure(bot, USER, "with_manager", "uz", CFG)  # сменил язык
    calls = bot.set_my_commands.await_args_list
    assert len(calls) == 3
    assert calls[1].kwargs["scope"] == BotCommandScopeChat(chat_id=USER)
    assert "human" not in [c.command for c in calls[1].args[0]]


async def run_middleware(
    bot: AsyncMock, client: FakeClientBot, event: Message, fsm: FSMContext
) -> None:
    data = {"bot": bot, "client_bot": client, "settings": FakeSettings(), "state": fsm}
    await ClientStatusMiddleware()(AsyncMock(), event, data)


async def test_phone_is_asked_once_with_a_contact_button() -> None:
    bot, client, fsm = fake_bot(), FakeClientBot(phone_due=True), state()
    for _ in range(3):
        await run_middleware(bot, client, message(bot, text="Хочу кассу"), fsm)
    assert client.asked == 1
    bot.send_message.assert_awaited_once()
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.one_time_keyboard
    assert markup.keyboard[0][0].request_contact is True
    assert markup.keyboard[1][0].text == CFG.texts.phone_skip_button.ru
    assert await fsm.get_state() == client_handlers.PhoneForm.pending.state


async def test_group_chats_are_left_alone() -> None:
    bot, client = fake_bot(), FakeClientBot(phone_due=True)
    await run_middleware(bot, client, message(bot, chat_type="group", text="привет"), state())
    assert client.asked == 0
    bot.set_my_commands.assert_not_awaited()


class RecordingConversation:
    """Запись в переписку CRM (менеджер должен видеть, что клиент поделился номером)."""

    def __init__(self) -> None:
        self.lead_messages: list[str] = []
        self.bot_replies: list[str] = []

    async def record_lead_message(self, inc: Any, meta: Any = None) -> int:
        self.lead_messages.append(inc.text)
        return 1

    async def record_bot_replies(self, tg_user_id: int, outgoing: list[Any]) -> None:
        self.bot_replies.extend(o.text for o in outgoing)


async def test_own_contact_is_saved_recorded_and_keyboard_removed() -> None:
    bot, client, fsm, conv = fake_bot(), FakeClientBot(), state(), RecordingConversation()
    await fsm.set_state(client_handlers.PhoneForm.pending)
    contact = {"phone_number": "998901234567", "first_name": "Азиз", "user_id": USER}
    event = message(bot, contact=contact)
    await client_handlers.on_own_contact(event, client, conv, FakeSettings(), fsm)  # type: ignore[arg-type]
    assert client.phones == ["+998901234567"]
    reply = sent(bot)[0]
    assert reply.text == CFG.texts.phone_saved.ru
    assert isinstance(reply.reply_markup, ReplyKeyboardRemove)
    assert await fsm.get_state() is None
    assert conv.lead_messages == ["📇 Азиз: 998901234567"]
    assert conv.bot_replies == [CFG.texts.phone_saved.ru]


@pytest.mark.parametrize(
    ("user_id", "own"),
    [(USER, True), (999, False), (None, False)],  # свой / чужой / контакт без Telegram-аккаунта
)
def test_only_own_contact_is_routed_to_the_phone_handler(user_id: int | None, own: bool) -> None:
    contact = {"phone_number": "+998901112233", "first_name": "Коллега", "user_id": user_id}
    # чужой контакт обрабатывает основной роутер — передаёт менеджеру текстом, как до Q-020
    assert client_handlers._own_contact(message(fake_bot(), contact=contact)) is own


async def test_not_now_removes_keyboard() -> None:
    bot, client, fsm = fake_bot(), FakeClientBot(), state()
    await fsm.set_state(client_handlers.PhoneForm.pending)
    event = message(bot, text=CFG.texts.phone_skip_button.ru)
    await client_handlers.on_phone_skip(event, client, FakeSettings(), fsm)
    reply = sent(bot)[0]
    assert reply.text == CFG.texts.phone_skipped.ru
    assert isinstance(reply.reply_markup, ReplyKeyboardRemove)
    assert await fsm.get_state() is None


async def test_prospect_gets_a_polite_explanation_for_client_commands() -> None:
    bot, client = fake_bot(), FakeClientBot()
    await client_handlers.on_docs(message(bot, text="/docs"), client, FakeSettings())
    assert sent(bot)[0].text == CFG.texts.client_only.ru


async def test_client_docs_are_inline_buttons_with_ids_only() -> None:
    bot = fake_bot()
    client = FakeClientBot(variant="client", client_id=5, docs=[(12, "Договор №7"), (9, "Акт")])
    await client_handlers.on_docs(message(bot, text="/docs"), client, FakeSettings())
    reply = sent(bot)[0]
    assert reply.text == CFG.texts.docs_list.ru
    assert isinstance(reply.reply_markup, InlineKeyboardMarkup)
    data = [row[0].callback_data for row in reply.reply_markup.inline_keyboard]
    assert data == ["doc:12", "doc:9"]
