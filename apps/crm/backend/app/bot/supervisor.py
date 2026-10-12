"""Бот в процессе API с перезапуском на лету (аудит 2026-10-12 §3, «Подключения»).

Диспетчер (агент, чекпоинтер, роутеры) собирается один раз; при смене токена
останавливается только `BotRuntime` (polling/webhook) и стартует новый с новым токеном —
без перезапуска API. Для webhook-эндпоинта супервизор выглядит как `BotRuntime`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import Dispatcher

from app.bot.runtime import BotRuntime
from app.config import Settings
from app.integrations.telegram import TokenSource

logger = structlog.get_logger(__name__)

TokenResolver = Callable[[], Awaitable[tuple[str, TokenSource]]]
DispatcherFactory = Callable[[], Awaitable[Dispatcher]]
RuntimeFactory = Callable[[Settings, Dispatcher, str], BotRuntime]


class BotSupervisor:
    def __init__(
        self,
        config: Settings,
        resolve: TokenResolver,
        dispatcher_factory: DispatcherFactory,
        runtime_factory: RuntimeFactory = BotRuntime.create,
    ) -> None:
        self._config = config
        self._resolve = resolve
        self._dispatcher_factory = dispatcher_factory
        self._runtime_factory = runtime_factory
        self._dispatcher: Dispatcher | None = None
        self._lock = asyncio.Lock()
        self.runtime: BotRuntime | None = None
        self.source: TokenSource = "none"
        self.username: str | None = None
        self.last_error: str | None = None

    @property
    def mode(self) -> str:
        return self._config.telegram_mode

    @property
    def running(self) -> bool:
        return self.runtime is not None

    async def start(self) -> None:
        async with self._lock:
            await self._launch()

    async def restart(self) -> None:
        """Остановить текущий бот и запустить с действующим токеном (после сохранения)."""
        async with self._lock:
            await self._halt(release_webhook=True)
            await self._launch()

    async def stop(self) -> None:
        async with self._lock:
            await self._halt(release_webhook=False)

    async def _launch(self) -> None:
        if self._config.telegram_mode == "disabled":
            return
        token, self.source = await self._resolve()
        if not token:
            logger.warning("bot_disabled", reason="no_token")
            return
        runtime: BotRuntime | None = None
        try:
            if self._dispatcher is None:
                self._dispatcher = await self._dispatcher_factory()
            runtime = self._runtime_factory(self._config, self._dispatcher, token)
            await runtime.start()
        except Exception as exc:  # noqa: BLE001 — сбой бота не роняет API; причина в статусе
            self.last_error = type(exc).__name__
            logger.error("bot_start_failed", source=self.source, error=self.last_error)
            if runtime is not None:
                await runtime.bot.session.close()
            return
        self.runtime, self.last_error = runtime, None
        try:
            me = await runtime.bot.get_me()
            self.username = me.username
        except Exception:
            logger.warning("bot_get_me_failed", exc_info=True)

    async def _halt(self, *, release_webhook: bool) -> None:
        runtime, self.runtime, self.username = self.runtime, None, None
        if runtime is not None:
            await runtime.stop(release_webhook=release_webhook)

    def secret_matches(self, received: str | None) -> bool:
        return self.runtime is not None and self.runtime.secret_matches(received)

    def feed(self, update: dict[str, Any]) -> None:
        if self.runtime is not None:
            self.runtime.feed(update)
