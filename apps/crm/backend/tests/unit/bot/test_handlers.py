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
