"""Интерфейс по статусу после каждого сообщения/кнопки лида (Q-011, Q-020).

После обработчика (статус мог измениться: /human, согласие, привязка клиента, взятие
менеджером) код пересчитывает меню чата и, один раз за жизнь лида, просит номер.
Пересчёт ленивый и идемпотентный: меню публикуется только при смене варианта.
"""

from typing import Any

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot import keyboards
from app.bot.client_handlers import PhoneForm
from app.bot.commands import ChatMenus
from app.bot.middlewares import Handler
from app.services.client_bot import ClientBotService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


def _private(event: TelegramObject) -> tuple[int, int] | None:
    """(chat_id, tg_user_id) личного чата; группы и канал команды — не трогаем."""
    if isinstance(event, Message) and event.chat.type == "private" and event.from_user:
        return event.chat.id, event.from_user.id
    message = event.message if isinstance(event, CallbackQuery) else None
    if isinstance(event, CallbackQuery) and message is not None and message.chat.type == "private":
        return message.chat.id, event.from_user.id
    return None


class ClientStatusMiddleware(BaseMiddleware):
    def __init__(self, menus: ChatMenus | None = None) -> None:
        self._menus = menus or ChatMenus()

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        target = _private(event)
        state: FSMContext | None = data.get("state")
        if target is not None and state is not None and isinstance(event, Message):
            text = event.text or ""
            if text.startswith("/") and not text.startswith("/request"):
                await state.clear()  # другая команда отменяет ожидание описания запроса
        result = await handler(event, data)
        client_bot: ClientBotService | None = data.get("client_bot")
        settings: SettingsService | None = data.get("settings")
        bot: Bot | None = data.get("bot")
        if target is None or client_bot is None or settings is None or bot is None:
            return result
        try:
            await self._refresh(bot, client_bot, settings, state, *target)
        except Exception:
            logger.exception("bot_status_refresh_failed", chat_id=target[0])
        return result

    async def _refresh(
        self,
        bot: Bot,
        client_bot: ClientBotService,
        settings: SettingsService,
        state: FSMContext | None,
        chat_id: int,
        tg_user_id: int,
    ) -> None:
        cfg = await settings.get()
        status = await client_bot.status(tg_user_id)
        await self._menus.ensure(bot, chat_id, status.variant, status.language, cfg)
        if not status.ask_phone:
            return
        # Флаг — до отправки: при сбое Telegram лучше не спросить, чем спросить дважды.
        await client_bot.mark_phone_asked(tg_user_id)
        await bot.send_message(
            chat_id,
            cfg.texts.phone_request.get(status.language),
            reply_markup=keyboards.phone_request(cfg, status.language),
        )
        if state is not None:
            await state.set_state(PhoneForm.pending)
        logger.info("bot_phone_requested", lead_id=status.lead_id)
