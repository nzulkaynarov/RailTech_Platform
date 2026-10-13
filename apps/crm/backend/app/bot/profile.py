"""Публикация профиля бота (имя, описание, краткое описание) в Telegram (ADR-0018).

Читаем текущие значения (`getMyName` и т. п.), меняем только отличия (`domain/bot_profile.py`):
у `setMyName`/`setMyDescription` жёсткий лимит частоты. Сбой не роняет бота — причина
словами в «Подключениях» (`ProfilePublish.error`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from app.domain.bot_profile import FIELDS, LANGUAGE_CODES, ProfileChange, Values, plan_changes
from app.schemas.settings_profile import BotProfileSettings

logger = structlog.get_logger(__name__)

PublishError = Literal["rate_limited", "telegram_error", "bot_not_running"]


@dataclass(frozen=True, slots=True)
class ProfilePublish:
    ok: bool
    at: datetime
    changed: int = 0
    error: PublishError | None = None
    retry_after: int | None = None


async def _current(bot: Bot) -> Values:
    values: Values = {}
    for code in LANGUAGE_CODES:
        values[("name", code)] = (await bot.get_my_name(language_code=code)).name
        values[("description", code)] = (
            await bot.get_my_description(language_code=code)
        ).description
        values[("short_description", code)] = (
            await bot.get_my_short_description(language_code=code)
        ).short_description
    return values


async def _apply(bot: Bot, change: ProfileChange) -> None:
    if change.field == "name":
        await bot.set_my_name(name=change.value, language_code=change.language_code)
    elif change.field == "description":
        await bot.set_my_description(description=change.value, language_code=change.language_code)
    else:
        await bot.set_my_short_description(
            short_description=change.value, language_code=change.language_code
        )


async def publish_profile(bot: Bot, profile: BotProfileSettings) -> ProfilePublish:
    """Опубликовать отличия профиля; без исключений — результат для статуса в CRM."""
    now = datetime.now(UTC)
    try:
        changes = plan_changes(profile.values(), await _current(bot))
        for change in changes:
            await _apply(bot, change)
    except TelegramRetryAfter as exc:
        logger.warning("bot_profile_rate_limited", retry_after=exc.retry_after)
        return ProfilePublish(False, now, error="rate_limited", retry_after=exc.retry_after)
    except Exception as exc:  # noqa: BLE001 — сбой сети/Telegram не роняет бота
        logger.warning("bot_profile_not_published", error=type(exc).__name__)
        return ProfilePublish(False, now, error="telegram_error")
    logger.info("bot_profile_published", changed=len(changes), fields=len(FIELDS))
    return ProfilePublish(True, now, changed=len(changes))
