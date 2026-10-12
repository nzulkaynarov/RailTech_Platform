"""Тексты из «Настроек», ответ при сбое агента и глобальный обработчик ошибок бота."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.types import ErrorEvent, Update
from pydantic import ValidationError

from app.bot.errors import COOLDOWN_S, ErrorReplier, private_chat
from app.schemas.settings import AppSettings, TextsSettings
from app.schemas.settings_base import LocalizedText
from app.services.conversation_support import failure_reply

CFG = AppSettings()


def _texts(**override: dict[str, str]) -> dict[str, Any]:
    data = TextsSettings().model_dump()
    for key, value in override.items():
        data[key] = {**data[key], **value}
    return data


def test_defaults_pass_placeholder_check() -> None:
    TextsSettings.model_validate(TextsSettings().model_dump())


@pytest.mark.parametrize(
    ("override", "path"),
    [
        ({"greeting": {"uz": "Salom, {kompaniya}!"}}, "greeting.uz"),
        ({"manager_joined": {"ru": "Здравствуйте!"}}, "manager_joined.ru"),
        ({"fallback": {"en": "No answer for {name}."}}, "fallback.en"),
        ({"request_created": {"ru": "Запрос №{number передан."}}, "request_created.ru"),
    ],
)
def test_admin_text_must_keep_default_placeholders(
    override: dict[str, dict[str, str]], path: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        TextsSettings.model_validate(_texts(**override))
    assert path in str(caught.value)


def test_localized_text_never_raises_on_missing_param() -> None:
    text = LocalizedText(ru="Привет, {company} и {name}", uz="x", en="y")
    assert text.get("ru", company="RT") == "Привет, RT и {name}"


def test_first_agent_failure_offers_manager() -> None:
    text, keyboard, meta = failure_reply(CFG, "ru", None)
    assert text == CFG.texts.service_unavailable.ru
    assert keyboard == "handoff_offer"
    assert meta == {"error": "agent_unavailable"}


@pytest.mark.parametrize("notice", ["handoff", "off_hours"])
def test_repeated_agent_failure_hands_over_without_apology(notice: str) -> None:
    text, keyboard, meta = failure_reply(CFG, "uz", notice)
    assert text == CFG.lead_notice(notice, "uz")  # type: ignore[arg-type]
    assert text != CFG.texts.service_unavailable.uz
    assert (keyboard, meta["notice"]) == (None, notice)


def _update(chat_type: str = "private", chat_id: int = 5) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": chat_id, "type": chat_type},
                "from": {"id": 77, "is_bot": False, "first_name": "A"},
                "text": "hi",
            },
        }
    )


def test_private_chat_only() -> None:
    assert private_chat(_update()) == (5, 77)
    assert private_chat(_update("channel", -100)) is None


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


async def test_error_handler_replies_once_per_chat_within_cooldown() -> None:
    clock = [0.0]
    replier = ErrorReplier(clock=lambda: clock[0])
    sender = _Sender()

    async def get() -> AppSettings:
        return CFG

    async def language_of(_user: int) -> str:
        return "en"

    deps: dict[str, Any] = {
        "bot": cast(Bot, sender),
        "settings": SimpleNamespace(get=get),
        "conversation": SimpleNamespace(language_of=language_of),
    }
    event = ErrorEvent(update=_update(), exception=RuntimeError("boom"))
    assert await replier.handle(event, **deps) is True
    assert await replier.handle(event, **deps) is True
    assert sender.sent == [(5, CFG.texts.service_unavailable.en)]
    clock[0] = COOLDOWN_S + 1
    await replier.handle(event, **deps)
    assert len(sender.sent) == 2
