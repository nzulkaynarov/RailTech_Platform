"""Разбор входящих Telegram-сообщений нетекстовых видов (аудит P-08)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import Message

from app.bot.attachments import media_of as _media
from app.bot.attachments import shared_text as _shared_text


def message(**content: Any) -> Message:
    return Message.model_validate(
        {
            "message_id": 7,
            "date": datetime(2026, 10, 9, tzinfo=UTC),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Азиз"},
            **content,
        }
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            {"voice": {"file_id": "v", "file_unique_id": "u", "duration": 3, "file_size": 10}},
            ("v", "voice.ogg", "audio/ogg", 10),
        ),
        (
            {"video_note": {"file_id": "n", "file_unique_id": "u", "length": 1, "duration": 2}},
            ("n", "video_note.mp4", "video/mp4", 0),
        ),
        (
            {
                "audio": {
                    "file_id": "a",
                    "file_unique_id": "u",
                    "duration": 5,
                    "file_name": "call.mp3",
                    "mime_type": "audio/mpeg",
                    "file_size": 99,
                }
            },
            ("a", "call.mp3", "audio/mpeg", 99),
        ),
        (
            {"document": {"file_id": "d", "file_unique_id": "u"}},
            ("d", "file", "application/octet-stream", 0),
        ),
        ({"sticker_like": None}, None),
    ],
)
def test_media(content: dict[str, Any], expected: tuple[str, str, str, int] | None) -> None:
    content.pop("sticker_like", None)
    assert _media(message(**content)) == expected


def test_contact_and_location_become_text() -> None:
    contact = message(contact={"phone_number": "+998901234567", "first_name": "Азиз"})
    location = message(location={"latitude": 41.311081, "longitude": 69.240562})
    assert _shared_text(contact) == "📇 Азиз: +998901234567"
    assert _shared_text(location) == "📍 41.31108, 69.24056"


# ── /start с параметром (D1-9) ─────────────────────────────────────────────────────────────────


class _Conversation:
    async def start(self, inc: Any) -> list[Any]:
        from app.services.conversation import Outgoing

        return [Outgoing("Здравствуйте!")]


class _StartLinks:
    def __init__(self, texts: list[str] | Exception) -> None:
        self.texts = texts
        self.calls: list[tuple[int, str]] = []

    async def apply(self, tg_user_id: int, payload: str) -> Any:
        self.calls.append((tg_user_id, payload))
        if isinstance(self.texts, Exception):
            raise self.texts
        return type("R", (), {"texts": self.texts})()


class _Settings:
    async def get(self) -> Any:
        from app.schemas.settings import AppSettings

        return AppSettings()


class _Bot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None) -> None:
        self.sent.append(text)


async def _start(args: str | None, links: _StartLinks | None) -> list[str]:
    from aiogram.filters import CommandObject

    from app.bot.handlers import on_start

    bot = _Bot()
    command = CommandObject(prefix="/", command="start", args=args)
    await on_start(message(text="/start"), bot, _Conversation(), _Settings(), command, links)
    return bot.sent


async def test_start_without_payload_just_greets() -> None:
    links = _StartLinks(["не должно прозвучать"])
    assert await _start(None, links) == ["Здравствуйте!"]
    assert links.calls == []


async def test_start_with_payload_adds_the_link_reply_after_the_greeting() -> None:
    links = _StartLinks(["Вижу вашу заявку."])
    assert await _start("deal_5", links) == ["Здравствуйте!", "Вижу вашу заявку."]
    assert links.calls == [(42, "deal_5")]


async def test_a_broken_link_never_breaks_the_greeting() -> None:
    assert await _start("web", _StartLinks(RuntimeError("boom"))) == ["Здравствуйте!"]


async def test_start_without_the_link_service_still_greets() -> None:
    assert await _start("web", None) == ["Здравствуйте!"]
