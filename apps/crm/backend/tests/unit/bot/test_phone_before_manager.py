"""Номер перед передачей по просьбе лида (решение владельца 2026-10-12) на подставном Bot.

Решение «спросить номер или передать» принимает `ClientBotService.hold_handoff_for_phone`
(домен `needs_phone_first`, таблица — `tests/unit/domain/test_handoff_gate.py`; запрос к БД —
`tests/integration/test_client_bot.py`). Здесь — что видит лид и что уходит в переписку.
"""

from dataclasses import dataclass, field
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.bot import client_handlers, handlers, keyboards
from app.schemas.settings import Language
from app.services.conversation_types import Incoming, Outgoing
from tests.unit.bot.test_client_menu import (
    CFG,
    USER,
    FakeSettings,
    RecordingConversation,
    fake_bot,
    message,
    sent,
    state,
)

NOTICE = "Передаю ваш вопрос менеджеру."


@dataclass
class GateClientBot:
    """`hold` — что вернул бы сервис: язык (ждём номер) или None (передаём как раньше)."""

    hold: Language | None = "ru"
    pending: bool = False
    phones: list[str] = field(default_factory=list)

    async def hold_handoff_for_phone(self, tg_user_id: int) -> Language | None:
        if self.hold is not None:
            self.pending = True
        return self.hold

    async def take_pending_handoff(self, tg_user_id: int) -> bool:
        was, self.pending = self.pending, False
        return was

    async def save_phone(self, tg_user_id: int, phone: str) -> None:
        self.phones.append(phone)

    async def status(self, tg_user_id: int) -> Any:
        return type("S", (), {"language": "ru"})()

    async def language_offer(self, tg_user_id: int, text: str) -> None:
        return None


class Conversation(RecordingConversation):
    """Переписка + ход диалога: `handle_message` с human_requested — это и есть передача."""

    def __init__(self) -> None:
        super().__init__()
        self.turns: list[Incoming] = []

    async def handle_message(self, inc: Incoming) -> list[Outgoing]:
        self.turns.append(inc)
        return [Outgoing(NOTICE, message_id=1)] if inc.human_requested else [Outgoing("ok")]

    async def language_of(self, tg_user_id: int) -> Language:
        return "ru"

    async def report_delivery_failure(self, lead_id: int) -> None:
        return None


def asked_for_phone(bot: AsyncMock) -> None:
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[1] == CFG.texts.phone_before_manager.ru
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.keyboard[0][0].request_contact is True


async def test_human_command_without_phone_asks_for_it_and_does_not_hand_off() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(), Conversation(), state()
    await handlers.on_human(message(bot, text="/human"), bot, conv, FakeSettings(), client, fsm)
    asked_for_phone(bot)
    assert conv.turns == []  # эскалация не создана
    assert conv.lead_messages == ["/human"]
    assert conv.bot_replies == [CFG.texts.phone_before_manager.ru]
    assert await fsm.get_state() == client_handlers.PhoneForm.pending.state


async def test_human_words_without_phone_ask_for_it() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(), Conversation(), state()
    event = message(bot, text="Позовите менеджера, пожалуйста")
    await handlers.on_text(event, bot, conv, FakeSettings(), client, fsm)
    asked_for_phone(bot)
    assert conv.turns == []


async def test_offer_yes_without_phone_asks_for_it() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(), Conversation(), state()
    query = CallbackQuery.model_validate(
        {
            "id": "1",
            "from": {"id": USER, "is_bot": False, "first_name": "Азиз"},
            "chat_instance": "c",
            "data": keyboards.OFFER_HUMAN,
            "message": message(bot, text="Не нашёл ответа. Позвать менеджера?").model_dump(),
        },
        context={"bot": bot},
    )
    await handlers.on_handoff_offer(query, bot, conv, FakeSettings(), client, fsm)
    asked_for_phone(bot)
    assert conv.turns == []
    assert conv.lead_messages == [CFG.texts.handoff_offer_yes.ru]


async def test_own_contact_after_request_hands_off_through_the_human_path() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(pending=True), Conversation(), state()
    await fsm.set_state(client_handlers.PhoneForm.pending)
    contact = {"phone_number": "998901234567", "first_name": "Азиз", "user_id": USER}
    await client_handlers.on_own_contact(
        message(bot, contact=contact),
        client,
        conv,
        FakeSettings(),
        fsm,
        bot,
    )
    assert client.phones == ["+998901234567"]
    assert not client.pending
    assert [t.human_requested for t in conv.turns] == [True]  # та же передача, что /human
    assert conv.turns[0].text == "📇 Азиз: 998901234567"
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[1] == NOTICE
    assert isinstance(bot.send_message.await_args.kwargs["reply_markup"], ReplyKeyboardRemove)


async def test_not_now_while_pending_declines_without_handoff() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(pending=True), Conversation(), state()
    await fsm.set_state(client_handlers.PhoneForm.pending)
    event = message(bot, text=CFG.texts.phone_skip_button.ru)
    await client_handlers.on_phone_skip(event, client, conv, FakeSettings(), fsm)
    reply = sent(bot)[0]
    assert reply.text == CFG.texts.phone_declined_manager.ru
    assert isinstance(reply.reply_markup, ReplyKeyboardRemove)
    assert conv.turns == []
    assert conv.bot_replies == [CFG.texts.phone_declined_manager.ru]
    assert not client.pending
    # Следующая просьба спрашивает номер снова (одноразовый `phone_asked_at` не мешает).
    await handlers.on_human(message(bot, text="/human"), bot, conv, FakeSettings(), client, fsm)
    asked_for_phone(bot)


async def test_no_gate_keeps_the_old_handoff() -> None:
    """Настройка выключена, номер уже есть или это клиент — сервис вернул None."""
    bot, client, conv, fsm = fake_bot(), GateClientBot(hold=None), Conversation(), state()
    await handlers.on_human(message(bot, text="/human"), bot, conv, FakeSettings(), client, fsm)
    assert [t.human_requested for t in conv.turns] == [True]
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[1] == NOTICE
    assert await fsm.get_state() is None


async def test_ordinary_text_is_not_gated() -> None:
    bot, client, conv, fsm = fake_bot(), GateClientBot(), Conversation(), state()
    await handlers.on_text(
        message(bot, text="Сколько стоит касса?"), bot, conv, FakeSettings(), client, fsm
    )
    assert [t.human_requested for t in conv.turns] == [False]
    assert not client.pending


class _Sessions:
    """Фабрика сессий для одного `async with sessions() as s, s.begin()`."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def __call__(self) -> "_Sessions":
        return self

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


async def test_phone_saved_after_system_handoff_refreshes_the_channel_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Номер пришёл после передачи по решению кода — карточка в канале перерисовывается."""
    from unittest.mock import AsyncMock, MagicMock

    from app.repositories import leads as leads_repo
    from app.services import client_bot as module

    refreshed: list[int] = []

    async def refresh(escalation_id: int) -> None:
        refreshed.append(escalation_id)

    identity = MagicMock(lead_id=7, phone_e164=None)
    session = MagicMock()
    session.scalar = AsyncMock(return_value=42)
    session.begin = MagicMock(return_value=AsyncMock())
    monkeypatch.setattr(leads_repo, "get_identity", AsyncMock(return_value=identity))
    # Склейка по номеру (M3-CRM-05) — отдельный сценарий integration; здесь совпадений нет.
    monkeypatch.setattr(module, "merge_by_phone", AsyncMock(return_value=None))
    svc = module.ClientBotService(
        cast(Any, _Sessions(session)), cast(Any, MagicMock()), on_card_changed=refresh
    )
    await svc.save_phone(1, "+998901234567")
    assert identity.phone_e164 == "+998901234567"
    assert refreshed == [42]
