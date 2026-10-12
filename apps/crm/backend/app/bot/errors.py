"""Глобальный обработчик ошибок бота (аудит 2026-10-12, SPEC §9.2).

Необработанное исключение в обработчике: лог + один раз `service_unavailable` в личный
чат. Повтор в тот же чат — не чаще `COOLDOWN_S`, чтобы сбой не превратился в спам.
"""

import time
from collections.abc import Callable
from typing import Any, Final

import structlog
from aiogram import Bot
from aiogram.types import ErrorEvent, Update

from app.services.conversation import ConversationService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

COOLDOWN_S: Final = 300.0


def private_chat(update: Update) -> tuple[int, int] | None:
    """(chat_id, tg_user_id) личного чата апдейта; канал и группы — None."""
    message = update.message or (
        update.callback_query.message if update.callback_query is not None else None
    )
    user = update.message.from_user if update.message else None
    if user is None and update.callback_query is not None:
        user = update.callback_query.from_user
    if message is None or user is None or message.chat.type != "private":
        return None
    return message.chat.id, user.id


class ErrorReplier:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: dict[int, float] = {}

    def should_reply(self, chat_id: int) -> bool:
        now = self._clock()
        last = self._last.get(chat_id)
        if last is not None and now - last < COOLDOWN_S:
            return False
        self._last[chat_id] = now
        return True

    async def __call__(
        self,
        event: ErrorEvent,
        bot: Bot,
        settings: SettingsService,
        conversation: ConversationService,
        **_: Any,
    ) -> bool:
        target = private_chat(event.update)
        logger.error(
            "tg_handler_failed",
            update_id=event.update.update_id,
            error=type(event.exception).__name__,
            exc_info=event.exception,
        )
        if target is None or not self.should_reply(target[0]):
            return True
        chat_id, user_id = target
        try:
            cfg = await settings.get()
            language = await conversation.language_of(user_id)
            await bot.send_message(chat_id, cfg.texts.service_unavailable.get(language))
        except Exception:
            logger.exception("tg_error_reply_failed", update_id=event.update.update_id)
        return True
