"""Выключатель Telegram (центр внешних сервисов, M3-CRM-12, ADR-0024): «технические работы».

Пока Telegram выключен вручную, клиент в личном чате на любое сообщение получает
`texts.maintenance` (не чаще раза в 10 минут на чат), диалог с ИИ не запускается, сообщение
сохраняется для команды. Нажатие кнопки — только снимает «часики». Канал команды не затрагивается.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.middlewares import Handler, SettingsProvider, _language, _record_silenced

logger = structlog.get_logger(__name__)
Paused = Callable[[], Awaitable[bool]]
WINDOW_S = 600.0


class MaintenanceMiddleware(BaseMiddleware):
    def __init__(
        self,
        paused: Paused,
        settings: SettingsProvider,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paused = paused
        self._settings = settings
        self._clock = clock
        self._told: dict[int, float] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        chat = _private_chat(event)
        if chat is None or not await self._paused():
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer()
            return None
        if not isinstance(event, Message):
            return await handler(event, data)
        await _record_silenced(event, data, meta={"maintenance": True})
        now = self._clock()
        if now - self._told.get(chat, -WINDOW_S * 2) >= WINDOW_S:
            self._told[chat] = now
            cfg = await self._settings()
            await event.answer(cfg.texts.maintenance.get(await _language(event, data)))
        logger.info("tg_maintenance_reply", chat_id=chat)
        return None


def _private_chat(event: TelegramObject) -> int | None:
    if isinstance(event, Message):
        return event.chat.id if event.chat.type == "private" else None
    if isinstance(event, CallbackQuery) and event.message is not None:
        chat = event.message.chat
        return chat.id if chat.type == "private" else None
    return None
