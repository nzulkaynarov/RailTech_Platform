"""Раздача событий `crm_events` подписчикам SSE в процессе API.

Одно соединение LISTEN на процесс; при обрыве — переподключение с паузой.
Медленный подписчик не тормозит остальных: при переполнении его очереди
событие для него отбрасывается (фронт всё равно перечитывает данные).
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import structlog

from app.repositories.events import CHANNEL

logger = structlog.get_logger(__name__)

QUEUE_SIZE = 100
RECONNECT_S = 3.0


class EventBroker:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def dispatch(self, payload: str) -> None:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    logger.info("event_broker_listening")
                    async for notify in conn.notifies():
                        self.dispatch(notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("event_broker_failed")
                await asyncio.sleep(RECONNECT_S)
