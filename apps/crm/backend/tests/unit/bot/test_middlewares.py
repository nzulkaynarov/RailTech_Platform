"""Rate-limit клиентского бота: окно 60 с, предупреждение не чаще раза в окно."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import Chat, Message, User

from app.bot.middlewares import RateLimitMiddleware
from app.schemas.settings import AppSettings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def message(language: str = "uz") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=5, type="private"),
        from_user=User(id=5, is_bot=False, first_name="A", language_code=language),
        text="salom",
    )


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    async def answer(self: Message, text: str, **_: Any) -> None:
        sent.append(text)

    monkeypatch.setattr(Message, "answer", answer)
    return sent


async def test_limits_messages_per_minute_and_warns_once(answers: list[str]) -> None:
    cfg = AppSettings.model_validate({"bot": {"rate_limit_per_minute": 2}})

    async def settings() -> AppSettings:
        return cfg

    clock = Clock()
    middleware = RateLimitMiddleware(settings, clock=clock)
    handled: list[int] = []

    async def handler(_event: Any, _data: dict[str, Any]) -> None:
        handled.append(1)

    for _ in range(4):
        await middleware(handler, message(), {})
    assert len(handled) == 2
    assert answers == [cfg.texts.rate_limited.get("uz")]

    clock.now += 61
    await middleware(handler, message(), {})
    assert len(handled) == 3


async def test_silenced_start_with_a_contact_link_is_stored_without_the_token(
    answers: list[str],
) -> None:
    """NOTIFY-1: заглушённый `/start tg_…` сохраняется для менеджера, но без токена."""
    cfg = AppSettings.model_validate({"bot": {"rate_limit_per_minute": 1}})

    async def settings() -> AppSettings:
        return cfg

    recorded: list[str] = []

    class Conversation:
        async def record_lead_message(self, inc: Any, meta: dict[str, Any]) -> None:
            recorded.append(inc.text)

        async def language_of(self, _tg_user_id: int) -> str:
            return "ru"

    token = "tg_" + "A1b2_-" * 8
    start = message().model_copy(update={"text": f"/start {token}"})

    async def handler(_event: Any, _data: dict[str, Any]) -> None:
        raise AssertionError("лимит исчерпан — обработчик не зовётся")

    handled: list[int] = []

    async def first(_event: Any, _data: dict[str, Any]) -> None:
        handled.append(1)

    middleware = RateLimitMiddleware(settings, clock=Clock())
    data = {"conversation": Conversation()}
    await middleware(first, message(), data)  # исчерпали лимит в минуту
    await middleware(handler, start, data)

    assert recorded == ["/start tg_***"]
    assert token not in recorded[0]
