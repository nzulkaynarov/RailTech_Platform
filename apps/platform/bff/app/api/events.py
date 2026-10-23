"""Поток подсказок инвалидации в браузер (контракт: tag `events`, operationId `streamEvents`).

SSE вместо опроса: на событие шины сотрудник получает `{"topics": [...], "reason": "<тип события>"}`
и сам перезапрашивает уведомления, счётчики и «Мою очередь» обычными API (с RBAC). Данных событий в
потоке нет. Всплеск событий сливается в одну подсказку (окно `PLATFORM_EVENTS_COALESCE_MS`), в
тишине идёт комментарий-heartbeat.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from app.config import Settings
from app.deps import Authed, require
from app.feeds.feed import drop_snapshots
from app.hub import EventHub, Hint
from app.session import SessionStore

router = APIRouter(tags=["events"])

# Как уведомления и очередь: раздел `dashboard.queue` открыт каждой роли.
StreamAuthed = Annotated[Authed, Depends(require("dashboard.queue", "read"))]

# `no-transform`: Caddy `encode` не буферизует поток; `X-Accel-Buffering` — то же для nginx.
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def frame(hint: Hint) -> str:
    return f"event: invalidate\ndata: {hint.dumps()}\n\n"


async def frames(
    hub: EventHub, store: SessionStore, redis: Redis, sid: str, settings: Settings
) -> AsyncIterator[str]:
    """Кадры SSE одного соединения; заканчивается, когда сессия сотрудника закрыта (выход, срок)."""
    stream = hub.attach(sid)
    try:
        yield ": connected\n\n"  # заголовки и первый байт сразу: браузер и прокси видят живой поток
        while True:
            if not await stream.wait(settings.events_heartbeat_seconds):
                if await store.get(sid) is None:
                    return
                yield ": ping\n\n"
                continue
            await asyncio.sleep(settings.events_coalesce_ms / 1000)
            hint = stream.take()
            if hint is None:
                continue
            # Сессию проверяем перед каждым кадром: при частых подсказках heartbeat не наступает,
            # а поток вышедшего сотрудника должен закрыться.
            if await store.get(sid) is None:
                return
            await drop_snapshots(redis, sid)
            yield frame(hint)
    finally:
        hub.detach(stream)


@router.get(
    "/events/stream",
    operation_id="streamEvents",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_events(request: Request, authed: StreamAuthed) -> StreamingResponse:
    hub: EventHub = request.app.state.hub
    settings: Settings = request.app.state.settings
    store = authed.service.store
    return StreamingResponse(
        frames(hub, store, store.redis, authed.sid, settings),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
