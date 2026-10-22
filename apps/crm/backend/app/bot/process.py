"""Процесс `crm-bot` (`python -m app bot`): приём Telegram отдельно от `crm-api` (S0-4, ADR-0017).

Здесь живёт всё входящее: long polling или webhook (`POST /telegram/webhook`, секретный заголовок
проверяется как раньше), диалоговый агент, `setWebhook` по `CRM_DOMAIN`. Перезапуск или падение
`crm-api` бота не трогает, и наоборот. Реплика ровно одна: второй потребитель `getUpdates`
получил бы `409 Conflict` от Telegram.

Исходящие сообщения шлют те, кому они нужны, своим клиентом Bot API (`Container.telegram_bot`):
воркер — уведомления команде и сообщения лидам из очереди, API — тест канала и публикация
профиля бота; `crm-bot` — ответы в диалогах и меню.

Связь с `crm-api` — через таблицу `bot_runtime` (`app/services/bot_state.py`): смена токена в
«Подключениях» сохраняется в БД и помечается запросом на перезапуск; `BotProcess` раз в
`BOT_POLL_INTERVAL_S` секунд видит его и перезапускает бота внутри процесса. Токен, сохранённый
любым другим путём, замечается по `integration_secrets.updated_at`.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog
from fastapi import FastAPI, Response, status

from app.api import telegram
from app.bot.setup import bot_lifespan
from app.bot.supervisor import BotSupervisor
from app.config import Settings, get_settings
from app.container import Container
from app.log import configure_logging
from app.security.secrets_store import TELEGRAM_BOT_TOKEN
from app.services.bot_state import BotStateService
from app.tasks.lifespan import queue_lifespan

logger = structlog.get_logger(__name__)


async def qualify_hook(lead_id: int) -> None:
    from app.tasks.qualify import enqueue_qualify

    await enqueue_qualify(lead_id)


async def escalated_hook(lead_id: int, escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id)


async def lead_message_hook(lead_id: int) -> None:
    from app.tasks.notify import enqueue_lead_message

    await enqueue_lead_message(lead_id)


class TokenStamp:
    """Метка последнего сохранения токена в «Подключениях»: смена метки — повод перезапуска."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def __call__(self) -> datetime | None:
        stored = await self._container.secrets_store.status(TELEGRAM_BOT_TOKEN)
        return stored.updated_at if stored is not None else None


class BotProcess:
    """Цикл процесса: старт бота, запросы на перезапуск из БД, повторные попытки, пульс."""

    def __init__(
        self,
        config: Settings,
        supervisor: BotSupervisor | None,
        state: BotStateService,
        token_stamp: TokenStamp,
    ) -> None:
        self._config = config
        self._supervisor = supervisor
        self._state = state
        self._token_stamp = token_stamp
        self._reported: tuple[object, ...] | None = None
        self._last_report = 0.0
        self._last_attempt = float("-inf")
        self._token_seen: datetime | None = None
        self.ticks = 0

    async def run(self) -> None:
        """Работает, пока процесс жив; сбой одного шага (БД, Telegram) не останавливает цикл."""
        await self._guard(self._boot)
        while True:
            await asyncio.sleep(self._config.bot_poll_interval_s)
            await self._guard(self._tick)

    async def _guard(self, step: Any) -> None:
        try:
            await step()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — процесс бота не должен падать из-за шага цикла
            logger.warning("bot_process_step_failed", step=step.__name__, error=type(exc).__name__)
        self.ticks += 1

    async def _boot(self) -> None:
        # Запрос, пришедший до старта, уже учтён свежим чтением токена при запуске; новый, пришедший
        # во время старта, будет отличаться от прочитанного здесь и сработает в следующем шаге.
        pending = await self._state.pending_restart()
        self._token_seen = await self._token_stamp()
        if self._supervisor is not None:
            await self._supervisor.start()
        self._last_attempt = time.monotonic()
        await self._report(started=True)
        if pending.pending and pending.requested_at is not None:
            await self._state.mark_applied(pending.requested_at)

    async def _tick(self) -> None:
        sup = self._supervisor
        if sup is None:  # TELEGRAM_MODE=disabled: процесс жив, бот не запускается
            await self._report()
            return
        pending = await self._state.pending_restart()
        stamp = await self._token_stamp()
        if pending.pending or stamp != self._token_seen:
            logger.info("bot_restart_requested", by="api" if pending.pending else "token_changed")
            self._token_seen = stamp
            await sup.restart()
            self._last_attempt = time.monotonic()
            await self._report()
            if pending.pending and pending.requested_at is not None:
                await self._state.mark_applied(pending.requested_at)
        elif not sup.running and time.monotonic() - self._last_attempt >= self._config.bot_retry_s:
            self._last_attempt = time.monotonic()
            await sup.recover()
            await self._report()
        else:
            await self._report()

    async def _report(self, *, started: bool = False) -> None:
        """Записать статус: сразу при изменении, иначе раз в `BOT_HEARTBEAT_S` (пульс)."""
        sup = self._supervisor
        facts: tuple[object, ...] = (
            (sup.running, sup.source, sup.username, sup.last_error, sup.profile)
            if sup is not None
            else (False, "none", None, None, None)
        )
        now = time.monotonic()
        if (
            not started
            and facts == self._reported
            and now - self._last_report < self._config.bot_heartbeat_s
        ):
            return
        await self._state.report(
            running=sup.running if sup is not None else False,
            mode=self._config.telegram_mode,
            source=sup.source if sup is not None else "none",
            username=sup.username if sup is not None else None,
            last_error=sup.last_error if sup is not None else None,
            profile=sup.profile if sup is not None else None,
            started=started,
        )
        self._reported, self._last_report = facts, now


def create_bot_app(settings: Settings | None = None) -> FastAPI:
    """ASGI-приложение процесса: приём webhook и liveness; сам бот — в `BotProcess`."""
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = Container(settings)
        try:
            async with (
                queue_lifespan(settings),
                bot_lifespan(
                    container,
                    on_activity=qualify_hook,
                    on_escalation=escalated_hook,
                    on_lead_message=lead_message_hook,
                ) as supervisor,
            ):
                process = BotProcess(
                    settings, supervisor, container.bot_state, TokenStamp(container)
                )
                app.state.bot = supervisor
                app.state.process = process
                loop = asyncio.create_task(process.run(), name="bot_process")
                app.state.loop = loop
                try:
                    yield
                finally:
                    loop.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await loop
        finally:
            await container.aclose()

    app = FastAPI(title="RailTech CRM Bot", version="0.1.0", lifespan=lifespan)
    app.include_router(telegram.router)

    @app.get("/health", include_in_schema=False)
    async def health(response: Response) -> dict[str, Any]:
        """Liveness: процесс жив и его цикл не упал. Недоступный Telegram — не повод перезапуска."""
        loop: asyncio.Task[None] | None = getattr(app.state, "loop", None)
        if loop is None or loop.done():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "fail"}
        supervisor = app.state.bot
        return {
            "status": "ok",
            "mode": settings.telegram_mode,
            "running": supervisor.running if supervisor is not None else False,
        }

    return app
