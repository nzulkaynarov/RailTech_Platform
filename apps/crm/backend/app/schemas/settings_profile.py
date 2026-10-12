"""Настройка `bot_profile`: имя и описания бота в Telegram на трёх языках (ADR-0018).

Правится в «Система → Подключения → Telegram-бот», публикуется через Bot API при сохранении
и при старте бота (`app/bot/profile.py`). Пустое русское значение — оставить как в BotFather.
"""

from typing import Self

from pydantic import Field, model_validator

from app.domain.bot_profile import FIELDS, LIMITS, Values
from app.schemas.settings_base import LANGUAGES, LocalizedText, StrictModel, localized


def _empty() -> LocalizedText:
    return localized("", "", "")


class BotProfileSettings(StrictModel):
    name: LocalizedText = Field(
        default_factory=_empty, description="Имя бота в Telegram, до 64 символов"
    )
    description: LocalizedText = Field(
        default_factory=_empty,
        description="«Что умеет этот бот?» — видно до /start, до 512 символов",
    )
    short_description: LocalizedText = Field(
        default_factory=_empty,
        description="Краткое описание в профиле бота и при пересылке, до 120 символов",
    )

    @model_validator(mode="after")
    def _telegram_limits(self) -> Self:
        for field, limit in LIMITS.items():
            text: LocalizedText = getattr(self, field)
            for language in LANGUAGES:
                if len(getattr(text, language)) > limit:
                    raise ValueError(f"{field}.{language}: не длиннее {limit} символов")
        return self

    def values(self) -> Values:
        """Значения по (поле, language_code); русский — значение по умолчанию (None)."""
        return {
            (field, None if language == "ru" else language): getattr(getattr(self, field), language)
            for field in FIELDS
            for language in LANGUAGES
        }
