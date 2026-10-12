"""Вложения и тихие ответы бота (аудит 2026-10-12): согласие, 20 МБ, rate-limit, запись в CRM."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import Message

from app.bot import handlers
from app.bot.middlewares import RateLimitMiddleware
from app.schemas.settings import AppSettings
from app.services.conversation import Incoming, Outgoing

CFG = AppSettings()


class FakeSettings:
    async def get(self) -> AppSettings:
        return CFG


class FakeConversation:
    def __init__(self, *, consented: bool = True) -> None:
        self.consented = consented
        self.handled: list[Incoming] = []
        self.recorded: list[tuple[Incoming, dict[str, Any] | None]] = []
        self.bot_replies: list[str] = []

    async def accepts_files(self, _uid: int) -> bool:
        return self.consented

    async def handle_message(self, inc: Incoming) -> list[Outgoing]:
        self.handled.append(inc)
        return []

    async def record_lead_message(
        self, inc: Incoming, meta: dict[str, Any] | None = None
    ) -> int | None:
        self.recorded.append((inc, meta))
        return 1

    async def record_bot_replies(self, _uid: int, out: list[Outgoing]) -> None:
        self.bot_replies.extend(item.text for item in out)

    async def language_of(self, _uid: int) -> str:
        return "ru"


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.downloads = 0

    async def send_message(self, _chat_id: int, text: str, **_: Any) -> None:
        self.sent.append(text)

    async def download(self, *_: Any, **__: Any) -> None:
        self.downloads += 1


class FakeStorage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def put(self, _bucket: str, key: str, *_: Any) -> None:
        self.keys.append(key)


def document(size: int) -> Message:
    return Message.model_validate(
        {
            "message_id": 9,
            "date": datetime(2026, 10, 12, tzinfo=UTC),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Азиз"},
            "document": {
                "file_id": "d",
                "file_unique_id": "u",
                "file_name": "plan.pdf",
                "file_size": size,
            },
        }
    )


async def attach(message: Message, conversation: FakeConversation) -> tuple[FakeBot, FakeStorage]:
    bot, storage = FakeBot(), FakeStorage()
    await handlers.on_attachment(
        message,
        bot,
        conversation,
        FakeSettings(),
        storage,
        "attachments",
    )
    return bot, storage


async def test_file_after_consent_is_uploaded() -> None:
    conversation = FakeConversation()
    bot, storage = await attach(document(1000), conversation)
    assert bot.downloads == 1
    assert storage.keys == ["tg/42/9/plan.pdf"]
    assert conversation.handled[0].attachments[0]["stored"] is True


async def test_file_before_consent_is_not_uploaded() -> None:
    conversation = FakeConversation(consented=False)
    bot, storage = await attach(document(1000), conversation)
    assert bot.downloads == 0
    assert storage.keys == []
    meta = conversation.handled[0].attachments[0]
    assert meta["stored"] is False
    assert meta["note"] == "файл получен до согласия"


async def test_file_over_20mb_gets_honest_reply_and_no_handoff() -> None:
    conversation = FakeConversation()
    bot, storage = await attach(document(21 * 1024 * 1024), conversation)
    too_large = CFG.texts.attachment_too_large.get("ru")
    assert bot.sent == [too_large]
    assert CFG.texts.attachment_received.get("ru") not in bot.sent
    assert conversation.handled == []  # нет хода диалога и эскалации «вложение»
    assert storage.keys == []
    assert bot.downloads == 0
    inc, _ = conversation.recorded[0]
    assert inc.attachments[0]["too_large"] is True
    assert conversation.bot_replies == [too_large]


async def test_contacts_reply_is_saved_after_the_lead_message() -> None:
    conversation = FakeConversation()
    message = Message.model_validate(
        {
            "message_id": 4,
            "date": datetime(2026, 10, 12, tzinfo=UTC),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Азиз"},
            "text": "дайте ваш телефон",
        }
    )
    out = await handlers._deterministic(
        message,
        "дайте ваш телефон",
        42,
        conversation,  # type: ignore[arg-type]
        FakeSettings(),  # type: ignore[arg-type]
    )
    assert out is not None
    assert [inc.text for inc, _ in conversation.recorded] == ["дайте ваш телефон"]
    assert conversation.bot_replies == [item.text for item in out]
    assert conversation.handled == []


async def test_rate_limited_message_is_still_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answer(self: Message, text: str, **_: Any) -> None:
        return None

    monkeypatch.setattr(Message, "answer", answer)
    cfg = AppSettings.model_validate({"bot": {"rate_limit_per_minute": 1}})

    async def settings() -> AppSettings:
        return cfg

    middleware = RateLimitMiddleware(settings, clock=lambda: 1000.0)
    conversation = FakeConversation()

    async def handler(_event: Any, _data: dict[str, Any]) -> None:
        return None

    text = Message.model_validate(
        {
            "message_id": 3,
            "date": datetime(2026, 10, 12, tzinfo=UTC),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Азиз"},
            "text": "алло",
        }
    )
    for _ in range(2):
        await middleware(handler, text, {"conversation": conversation})
    assert [(inc.text, meta) for inc, meta in conversation.recorded] == [
        ("алло", {"rate_limited": True})
    ]
