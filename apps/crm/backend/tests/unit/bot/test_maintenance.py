"""Выключатель Telegram (M3-CRM-12, ADR-0024): «технические работы» вместо диалога."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.maintenance import WINDOW_S, MaintenanceMiddleware
from app.schemas.settings import AppSettings

CFG = AppSettings()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Flag:
    def __init__(self, paused: bool) -> None:
        self.paused = paused

    async def __call__(self) -> bool:
        return self.paused


async def settings() -> AppSettings:
    return CFG


def message(chat_type: str = "private", language: str = "en") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=-100 if chat_type == "channel" else 7, type=chat_type),
        from_user=User(id=7, is_bot=False, first_name="A", language_code=language),
        text="hello",
    )


class Conversation:
    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    async def record_lead_message(self, inc: Any, meta: dict[str, Any]) -> None:
        self.recorded.append(meta)

    async def language_of(self, tg_user_id: int) -> str:
        return "en"


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    async def answer(self: Message, text: str, **_: Any) -> None:
        sent.append(text)

    monkeypatch.setattr(Message, "answer", answer)
    return sent


async def test_paused_bot_answers_maintenance_once_per_window_and_keeps_message(
    answers: list[str],
) -> None:
    clock = Clock()
    middleware = MaintenanceMiddleware(Flag(True), settings, clock=clock)
    handled: list[int] = []
    conversation = Conversation()

    async def handler(_event: Any, _data: dict[str, Any]) -> None:
        handled.append(1)

    for _ in range(3):
        await middleware(handler, message(), {"conversation": conversation})
    assert handled == []
    assert answers == [CFG.texts.maintenance.get("en")]
    assert conversation.recorded == [{"maintenance": True}] * 3

    clock.now += WINDOW_S
    await middleware(handler, message(), {"conversation": conversation})
    assert len(answers) == 2


async def test_running_bot_and_team_channel_are_untouched(answers: list[str]) -> None:
    handled: list[str] = []

    async def handler(event: Any, _data: dict[str, Any]) -> None:
        handled.append(event.chat.type)

    await MaintenanceMiddleware(Flag(False), settings)(handler, message(), {})
    await MaintenanceMiddleware(Flag(True), settings)(handler, message("channel"), {})
    assert handled == ["private", "channel"]
    assert answers == []


async def test_paused_bot_button_press_only_stops_spinner(monkeypatch: pytest.MonkeyPatch) -> None:
    answered: list[bool] = []

    async def answer(self: CallbackQuery, *args: Any, **kwargs: Any) -> None:
        answered.append(True)

    monkeypatch.setattr(CallbackQuery, "answer", answer)
    query = CallbackQuery(
        id="1",
        from_user=User(id=7, is_bot=False, first_name="A"),
        chat_instance="x",
        message=message(),
        data="menu",
    )

    async def handler(_event: Any, _data: dict[str, Any]) -> None:
        raise AssertionError("handler must not run while paused")

    assert await MaintenanceMiddleware(Flag(True), settings)(handler, query, {}) is None
    assert answered == [True]


def test_maintenance_text_exists_in_three_languages() -> None:
    text = CFG.texts.maintenance
    assert all(text.get(lang) for lang in ("ru", "uz", "en"))
    assert "Технические работы" in text.get("ru") or "технические работы" in text.get("ru")
