"""Запуск клиентского бота: long polling (dev) или webhook (prod) — SPEC §9.2, §13.

Апдейт проходит: IdempotencyMiddleware (`tg_updates`) → RateLimitMiddleware →
MaintenanceMiddleware (выключатель Telegram, ADR-0024) → ClientStatusMiddleware
(меню и номер по статусу, Q-011/Q-020) → обработчики
`app/bot/client_handlers.py`, затем `app/bot/handlers.py`. В режиме webhook `crm-bot` отвечает
Telegram сразу, а апдейт обрабатывается в фоне.
"""

import asyncio
import hmac
from typing import Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import channel, chat_member, client_handlers, commands, handlers
from app.bot.errors import ErrorReplier
from app.bot.maintenance import MaintenanceMiddleware, Paused
from app.bot.middlewares import IdempotencyMiddleware, RateLimitMiddleware
from app.bot.profile import ProfilePublish, publish_profile
from app.bot.status import ClientStatusMiddleware
from app.config import Settings
from app.domain.telegram_webhook import webhook_url_problem
from app.integrations.s3 import ObjectStorage
from app.integrations.telegram import make_bot
from app.schemas.settings_profile import BotProfileSettings
from app.security.rbac import Rbac
from app.services.client_bot import ClientBotService
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
    client_bot: ClientBotService | None = None,
    telegram_paused: Paused | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(
        conversation=conversation,
        settings=settings,
        object_storage=storage,
        attachments_bucket=attachments_bucket,
        sessions=sessions,
        leads=leads,
        rbac=rbac,
        client_bot=client_bot or ClientBotService(sessions, settings),
    )
    dispatcher.update.outer_middleware(IdempotencyMiddleware(sessions))
    dispatcher.message.outer_middleware(RateLimitMiddleware(settings.get))
    if telegram_paused is not None:
        # Выключатель Telegram (ADR-0024): «технические работы» вместо диалога.
        maintenance = MaintenanceMiddleware(telegram_paused, settings.get)
        dispatcher.message.outer_middleware(maintenance)
        dispatcher.callback_query.outer_middleware(maintenance)
    status = ClientStatusMiddleware()
    dispatcher.message.outer_middleware(status)
    dispatcher.callback_query.outer_middleware(status)
    if leads is not None and rbac is not None:
        dispatcher.include_router(channel.router)
    dispatcher.include_router(client_handlers.router)
    dispatcher.include_router(chat_member.router)
    dispatcher.include_router(handlers.router)
    # Сбой обработчика: лог и одно «не получается ответить» на чат, а не тишина (аудит).
    dispatcher.errors.register(ErrorReplier().handle)
    return dispatcher


class WebhookNotConfiguredError(Exception):
    """`TELEGRAM_MODE=webhook` без годного https-адреса: бот не запускается (FIX-66)."""

    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


def webhook_config_problem(config: Settings) -> str | None:
    """Режим webhook с пустым или не-https адресом — `empty` / `not_https`; иначе `None`."""
    if config.telegram_mode != "webhook":
        return None
    return webhook_url_problem(config.telegram_webhook_url)


class BotRuntime:
    def __init__(self, config: Settings, bot: Bot, dispatcher: Dispatcher) -> None:
        self._config = config
        self.bot = bot
        self.dispatcher = dispatcher
        self._polling: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[Any]] = set()
        self.profile: ProfilePublish | None = None

    @classmethod
    def create(cls, config: Settings, dispatcher: Dispatcher, token: str) -> "BotRuntime":
        """`token` — действующий токен (БД «Подключения» или env, `integrations/telegram.py`)."""
        bot = make_bot(config, token, default=DefaultBotProperties(link_preview_is_disabled=True))
        return cls(config, bot, dispatcher)

    async def start(self) -> None:
        # Первым делом и до любых вызовов Bot API: `set_webhook("")` молча удалял вебхук (FIX-66).
        problem = webhook_config_problem(self._config)
        if problem is not None:
            raise WebhookNotConfiguredError(problem)
        allowed = self.dispatcher.resolve_used_update_types()
        settings = self.dispatcher.workflow_data.get("settings")
        cfg = await settings.get() if settings else None
        await commands.publish(self.bot, cfg)
        self.profile = await publish_profile(
            self.bot, cfg.bot_profile if cfg else BotProfileSettings()
        )
        if self._config.telegram_mode == "polling":
            await self.bot.delete_webhook(drop_pending_updates=False)
            self._polling = asyncio.create_task(
                self.dispatcher.start_polling(
                    self.bot, allowed_updates=allowed, handle_signals=False, close_bot_session=False
                )
            )
        else:
            await self.bot.set_webhook(
                self._config.telegram_webhook_url.strip(),
                secret_token=self._config.telegram_webhook_secret.get_secret_value(),
                allowed_updates=allowed,
            )
        logger.info("bot_started", mode=self._config.telegram_mode, updates=allowed)

    async def stop(self, *, release_webhook: bool = False) -> None:
        """`release_webhook` — при смене токена: старый бот больше не шлёт апдейты на наш URL."""
        if self._polling is not None:
            if not self._polling.done():  # упавший polling уже остановлен: stop_polling бросил бы
                await self.dispatcher.stop_polling()
            await asyncio.gather(self._polling, return_exceptions=True)
            self._polling = None
        if self._background:
            await asyncio.wait(self._background, timeout=10)
        if release_webhook and self._config.telegram_mode == "webhook":
            try:
                await self.bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                logger.warning("bot_webhook_release_failed", exc_info=True)
        await self.bot.session.close()

    @property
    def running(self) -> bool:
        """Бот принимает обновления: polling-задача жива или включён webhook."""
        if self._config.telegram_mode == "webhook":
            return True
        return self._polling is not None and not self._polling.done()

    @property
    def failure(self) -> str | None:
        """Класс исключения, которым упал polling; `None` — не упал."""
        task = self._polling
        if task is None or not task.done() or task.cancelled():
            return None
        exc = task.exception()
        return type(exc).__name__ if exc is not None else None

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
