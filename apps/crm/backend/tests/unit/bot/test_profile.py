"""Профиль бота: лимиты Telegram, только отличия, ошибки словами — без сети (фейковый Bot)."""

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SetMyName
from pydantic import ValidationError

from app.bot.profile import publish_profile
from app.domain.bot_profile import ProfileChange, plan_changes
from app.schemas.settings import SETTINGS_MODELS, AppSettings
from app.schemas.settings_profile import BotProfileSettings


def profile(**fields: tuple[str, str, str]) -> BotProfileSettings:
    return BotProfileSettings.model_validate(
        {
            name: dict(zip(("ru", "uz", "en"), values, strict=True))
            for name, values in fields.items()
        }
    )


class FakeBot:
    """Хранит профиль как Telegram: значение языка или значение по умолчанию."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.values: dict[tuple[str, str | None], str] = {("name", None): "BotFather name"}
        self.calls: list[tuple[str, str | None, str]] = []
        self.fail = fail

    def _get(self, field: str, code: str | None) -> str:
        return self.values.get((field, code)) or self.values.get((field, None), "")

    def _set(self, field: str, value: str, code: str | None) -> bool:
        if self.fail is not None:
            raise self.fail
        self.calls.append((field, code, value))
        self.values[(field, code)] = value
        return True

    async def get_my_name(self, language_code: str | None = None) -> Any:
        return SimpleNamespace(name=self._get("name", language_code))

    async def get_my_description(self, language_code: str | None = None) -> Any:
        return SimpleNamespace(description=self._get("description", language_code))

    async def get_my_short_description(self, language_code: str | None = None) -> Any:
        return SimpleNamespace(short_description=self._get("short_description", language_code))

    async def set_my_name(self, name: str, language_code: str | None = None) -> bool:
        return self._set("name", name, language_code)

    async def set_my_description(self, description: str, language_code: str | None = None) -> bool:
        return self._set("description", description, language_code)

    async def set_my_short_description(
        self, short_description: str, language_code: str | None = None
    ) -> bool:
        return self._set("short_description", short_description, language_code)


def test_registered_as_settings_key_with_empty_defaults() -> None:
    assert SETTINGS_MODELS["bot_profile"] is BotProfileSettings
    assert AppSettings().bot_profile.name.ru == ""


@pytest.mark.parametrize(
    ("field", "limit"), [("name", 64), ("description", 512), ("short_description", 120)]
)
def test_telegram_limits(field: str, limit: int) -> None:
    BotProfileSettings.model_validate({field: {"ru": "я" * limit, "uz": "", "en": ""}})
    with pytest.raises(ValidationError, match=f"{field}.en"):
        BotProfileSettings.model_validate({field: {"ru": "", "uz": "", "en": "a" * (limit + 1)}})


@pytest.mark.parametrize(
    ("desired", "current", "expected"),
    [
        # Пустой русский — не трогаем BotFather; пустой язык, совпадающий с русским, — тоже.
        ({}, {("name", None): "X", ("name", "uz"): "X", ("name", "en"): "X"}, []),
        (
            {("name", None): "RailTech"},
            {("name", None): "X", ("name", "uz"): "X", ("name", "en"): "X"},
            [ProfileChange("name", None, "RailTech")],
        ),
        (
            {("description", None): "Привет", ("description", "uz"): "Salom"},
            {
                ("description", None): "Привет",
                ("description", "uz"): "Salom",
                ("description", "en"): "Привет",
            },
            [],
        ),
        # Отдельный английский текст убран в CRM — убираем и в Telegram.
        (
            {("short_description", None): "Р"},
            {
                ("short_description", None): "Р",
                ("short_description", "uz"): "Р",
                ("short_description", "en"): "E",
            },
            [ProfileChange("short_description", "en", "")],
        ),
    ],
)
def test_plan_changes(
    desired: dict[Any, str], current: dict[Any, str], expected: list[ProfileChange]
) -> None:
    assert plan_changes(desired, current) == expected


async def test_publish_sets_languages_then_is_idempotent() -> None:
    bot = FakeBot()
    wanted = profile(
        name=("RailTech ассистент", "RailTech yordamchi", "RailTech assistant"),
        description=("Отвечаю на вопросы", "", ""),
    )
    result = await publish_profile(bot, wanted)  # type: ignore[arg-type]
    assert (result.ok, result.error) == (True, None)
    assert ("name", None, "RailTech ассистент") in bot.calls
    assert ("name", "uz", "RailTech yordamchi") in bot.calls
    assert ("description", None, "Отвечаю на вопросы") in bot.calls
    assert not any(field == "short_description" for field, _, _ in bot.calls)

    bot.calls.clear()
    again = await publish_profile(bot, wanted)  # type: ignore[arg-type]
    assert (again.ok, again.changed, bot.calls) == (True, 0, [])


async def test_rate_limit_reported_in_words() -> None:
    error = TelegramRetryAfter(method=SetMyName(name="x"), message="Too Many", retry_after=600)
    bot = FakeBot(fail=error)
    result = await publish_profile(bot, profile(name=("Новое", "", "")))  # type: ignore[arg-type]
    assert not result.ok
    assert (result.error, result.retry_after) == ("rate_limited", 600)


async def test_network_failure_does_not_raise() -> None:
    bot = FakeBot(fail=OSError("down"))
    result = await publish_profile(bot, profile(name=("Новое", "", "")))  # type: ignore[arg-type]
    assert (result.ok, result.error) == (False, "telegram_error")
