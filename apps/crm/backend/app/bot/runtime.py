"""Запуск клиентского бота: long polling (dev) или webhook (prod) — SPEC §9.2, §13.

Апдейт проходит: IdempotencyMiddleware (`tg_updates`) → RateLimitMiddleware →
обработчики `app/bot/handlers.py`. В режиме webhook API отвечает Telegram
сразу, а апдейт обрабатывается в фоне.
"""

import asyncio
import hmac
from typing import Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import channel, commands, handlers
from app.bot.middlewares import IdempotencyMiddleware, RateLimitMiddleware
from app.config import Settings
from app.integrations.s3 import ObjectStorage
from app.security.rbac import Rbac
from app.services.conversation import ConversationService
from app.services.leads import LeadService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)


def build_dispatcher(
    sessions: async_sessionmaker[AsyncSession],
    conversation: ConversationService,
    settings: SettingsService,
    storage: ObjectStorage,
    attachments_bucket: str,
    leads: LeadService | None = None,
    rbac: Rbac | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(
        conversation=conversation,
        settings=settings,
        object_storage=storage,
        attachments_bucket=attachments_bucket,
        sessions=sessions,
        leads=leads,
        rbac=rbac,
    )
    dispatcher.update.outer_middleware(IdempotencyMiddleware(sessions))
    dispatcher.message.outer_middleware(RateLimitMiddleware(settings.get))
    if leads is not None and rbac is not None:
        dispatcher.include_router(channel.router)
    dispatcher.include_router(handlers.router)
    return dispatcher


class BotRuntime:
    def __init__(self, config: Settings, bot: Bot, dispatcher: Dispatcher) -> None:
        self._config = config
        self.bot = bot
        self.dispatcher = dispatcher
        self._polling: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[Any]] = set()

    @classmethod
    def create(cls, config: Settings, dispatcher: Dispatcher) -> "BotRuntime":
        bot = Bot(
            config.telegram_bot_token.get_secret_value(),
            default=DefaultBotProperties(link_preview_is_disabled=True),
        )
        return cls(config, bot, dispatcher)

    async def start(self) -> None:
        allowed = self.dispatcher.resolve_used_update_types()
        await commands.publish(self.bot)
        if self._config.telegram_mode == "polling":
            await self.bot.delete_webhook(drop_pending_updates=False)
            self._polling = asyncio.create_task(
                self.dispatcher.start_polling(
                    self.bot, allowed_updates=allowed, handle_signals=False, close_bot_session=False
                )
            )
        else:
            await self.bot.set_webhook(
                self._config.telegram_webhook_url,
                secret_token=self._config.telegram_webhook_secret.get_secret_value(),
                allowed_updates=allowed,
            )
        logger.info("bot_started", mode=self._config.telegram_mode, updates=allowed)

    async def stop(self) -> None:
        if self._polling is not None:
            await self.dispatcher.stop_polling()
            await asyncio.gather(self._polling, return_exceptions=True)
        if self._background:
            await asyncio.wait(self._background, timeout=10)
        await self.bot.session.close()

    @property
    def running(self) -> bool:
        """Бот принимает обновления: polling-задача жива или включён webhook."""
        if self._config.telegram_mode == "webhook":
            return True
        return self._polling is not None and not self._polling.done()

    def secret_matches(self, received: str | None) -> bool:
        expected = self._config.telegram_webhook_secret.get_secret_value()
        if self._config.telegram_mode != "webhook" or not expected:
            return False
        return hmac.compare_digest((received or "").encode(), expected.encode())

    def feed(self, update: dict[str, Any]) -> None:
        """Обработать апдейт webhook в фоне; ответ Telegram не ждёт агента."""
        task = asyncio.create_task(self._feed(update))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _feed(self, update: dict[str, Any]) -> None:
        try:
            await self.dispatcher.feed_webhook_update(self.bot, update)
        except Exception:
            logger.exception("tg_update_failed", update_id=update.get("update_id"))
