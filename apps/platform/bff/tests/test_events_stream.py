"""Поток подсказок (B5): SSE `/api/v1/events/stream`, слияние всплесков, heartbeat, кэш, pub/sub."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI

from app.api.events import frame, frames
from app.config import Settings
from app.hub import CHANNEL, TOPICS, EventHub, Hint
from tests.bus_support import SECRET, delivery, envelope
from tests.conftest import Web
from tests.fakes import Clock, FakeRedis
from tests.roles import custom

FAST = {"PLATFORM_EVENTS_COALESCE_MS": 30, "PLATFORM_EVENTS_HEARTBEAT_SECONDS": 0.2}


def fast_settings(**extra: Any) -> Settings:
    return Settings(**{**FAST, **extra})


async def until(predicate: Callable[[], bool], seconds: float = 2.0) -> None:
    async with asyncio.timeout(seconds):
        while not predicate():  # noqa: ASYNC110 — опрос условия теста
            await asyncio.sleep(0.005)


class Reader:
    """Читает кадры одного соединения в фоне и складывает их в список."""

    def __init__(self, stream: AsyncIterator[str]) -> None:
        self.frames: list[str] = []
        self.done = asyncio.Event()
        self._stream = stream
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async for item in self._stream:
                self.frames.append(item)
        finally:
            self.done.set()

    def events(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.frames:
            if item.startswith("event: invalidate"):
                out.append(json.loads(item.split("data: ", 1)[1]))
        return out

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(Clock())


@pytest.fixture
async def hub(redis: FakeRedis) -> AsyncIterator[EventHub]:
    instance = EventHub(lambda: redis)  # type: ignore[arg-type,return-value]
    yield instance
    await instance.aclose()


class StubStore:
    """Хранилище сессий: сессия жива, пока `alive` (настоящее — в тестах маршрута)."""

    def __init__(self) -> None:
        self.alive = True

    async def get(self, sid: str) -> object | None:
        return object() if self.alive else None


@pytest.fixture
def store() -> StubStore:
    return StubStore()


def open_stream(
    hub: EventHub, store: StubStore, redis: FakeRedis, sid: str = "sid-1", **extra: Any
) -> Reader:
    return Reader(frames(hub, store, redis, sid, fast_settings(**extra)))  # type: ignore[arg-type]


def test_frame_is_a_named_event_with_the_hint_as_data() -> None:
    assert frame(Hint(("queue", "counters"), "uz.railtech.erp.quote.sent.v1")) == (
        'event: invalidate\ndata: {"topics": ["queue", "counters"], '
        '"reason": "uz.railtech.erp.quote.sent.v1"}\n\n'
    )


async def test_first_frame_flushes_the_headers_at_once(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    reader = open_stream(hub, store, redis)
    await until(lambda: reader.frames == [": connected\n\n"])
    await reader.close()


async def test_hint_reaches_the_open_stream_through_redis(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    reader = open_stream(hub, store, redis)
    await until(lambda: bool(redis.subscribers))
    await hub.publish(Hint(("notifications", "counters"), "uz.railtech.erp.invoice.paid.v1"))
    await until(lambda: bool(reader.events()))
    assert reader.events() == [
        {"topics": ["notifications", "counters"], "reason": "uz.railtech.erp.invoice.paid.v1"}
    ]
    assert redis.published[0][0] == CHANNEL
    await reader.close()


async def test_a_burst_is_merged_into_one_frame(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    reader = open_stream(hub, store, redis, PLATFORM_EVENTS_COALESCE_MS=150)
    await until(lambda: bool(redis.subscribers))
    for topics, reason in (
        (("notifications",), "uz.railtech.erp.quote.sent.v1"),
        (("queue",), "uz.railtech.crm.lead.created.v1"),
        (("notifications", "counters"), "uz.railtech.erp.invoice.paid.v1"),
    ):
        await hub.publish(Hint(topics, reason))
    await until(lambda: bool(reader.events()))
    await asyncio.sleep(0.3)
    assert reader.events() == [
        {
            "topics": ["notifications", "counters", "queue"],
            "reason": "uz.railtech.erp.invoice.paid.v1",
        }
    ]
    await reader.close()


async def test_every_open_stream_gets_the_hint_and_a_closed_one_does_not(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    first = open_stream(hub, store, redis, "sid-1")
    second = open_stream(hub, store, redis, "sid-2")
    await until(lambda: bool(redis.subscribers) and hub.streams == 2)
    await first.close()
    await until(lambda: hub.streams == 1)
    await hub.publish(Hint(TOPICS, "uz.railtech.erp.act.issued.v1"))
    await until(lambda: bool(second.events()))
    assert first.events() == []
    await second.close()
    await until(lambda: hub.streams == 0)


async def test_silence_is_filled_with_heartbeat_comments(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    reader = open_stream(hub, store, redis)
    await until(lambda: reader.frames.count(": ping\n\n") >= 2)
    assert reader.events() == []
    await reader.close()


async def test_stream_ends_when_the_session_is_gone(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    store.alive = False  # выход или истёкший срок
    reader = open_stream(hub, store, redis, "sid-gone")
    async with asyncio.timeout(2):
        await reader.done.wait()
    assert hub.streams == 0


async def test_stream_ends_on_a_hint_when_the_session_is_gone_even_without_heartbeat(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    """Выход при потоке подсказок: без heartbeat кадр вышедшему не уходит, поток закрывается."""
    redis.values["feed:sid-1:data:erp:/x:{}"] = "[]"
    reader = open_stream(hub, store, redis, PLATFORM_EVENTS_HEARTBEAT_SECONDS=60)
    await until(lambda: bool(redis.subscribers))
    await hub.publish(Hint(("queue",), "first"))
    await until(lambda: bool(reader.events()))
    store.alive = False  # выход
    await hub.publish(Hint(("queue",), "second"))
    async with asyncio.timeout(2):
        await reader.done.wait()
    assert [e["reason"] for e in reader.events()] == ["first"]
    assert hub.streams == 0


async def test_hint_drops_the_session_feed_cache_but_not_the_others(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    redis.values["feed:sid-1:data:erp:/api/v1/notifications/:{}"] = "[]"
    redis.values["feed:sid-1:refused:erp:/x:{}"] = "1"
    redis.values["feed:sid-2:data:erp:/api/v1/notifications/:{}"] = "[]"
    reader = open_stream(hub, store, redis, "sid-1")
    await until(lambda: bool(redis.subscribers))
    await hub.publish(Hint(("queue",), "uz.railtech.crm.lead.updated.v1"))
    await until(lambda: bool(reader.events()))
    assert "feed:sid-1:data:erp:/api/v1/notifications/:{}" not in redis.values
    assert "feed:sid-1:refused:erp:/x:{}" in redis.values
    assert "feed:sid-2:data:erp:/api/v1/notifications/:{}" in redis.values
    await reader.close()


async def test_listener_survives_a_redis_outage_and_asks_for_a_full_refresh(
    hub: EventHub, store: StubStore, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.hub.RECONNECT_MIN_SECONDS", 0.02)
    monkeypatch.setattr("app.hub.LISTEN_POLL_SECONDS", 0.02)
    reader = open_stream(hub, store, redis)
    await until(lambda: bool(redis.subscribers))
    redis.pubsub_down = True  # обрыв: слушатель падает и ждёт
    await asyncio.sleep(0.1)
    assert reader.events() == []
    redis.pubsub_down = False  # Redis вернулся: слушатель подписывается снова
    await until(lambda: bool(reader.events()))
    assert reader.events() == [{"topics": list(TOPICS), "reason": "resync"}]
    await hub.publish(Hint(("queue",), "uz.railtech.erp.quote.sent.v1"))
    await until(lambda: len(reader.events()) == 2)
    await reader.close()


async def test_garbage_in_the_channel_is_ignored(
    hub: EventHub, store: StubStore, redis: FakeRedis
) -> None:
    reader = open_stream(hub, store, redis)
    await until(lambda: bool(redis.subscribers))
    for junk in ("not json", '{"topics": ["secrets"], "reason": "x"}', '{"topics": []}'):
        await redis.publish(CHANNEL, junk)
    await hub.publish(Hint(("queue",), "ok"))
    await until(lambda: bool(reader.events()))
    assert reader.events() == [{"topics": ["queue"], "reason": "ok"}]
    await reader.close()


# --- маршрут GET /api/v1/events/stream поверх ASGI ------------------------------------------------


class Asgi:
    """Сырое ASGI-соединение: httpx буферизует тело до конца, а поток бесконечен."""

    def __init__(self, app: FastAPI, path: str, cookie: str | None) -> None:
        self.start: dict[str, Any] = {}
        self.body = b""
        self.chunks: list[bytes] = []
        self._disconnect = asyncio.Event()
        headers = [(b"host", b"bff.test")]
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "server": ("bff.test", 443),
            "client": ("203.0.113.9", 1234),
        }
        self.task = asyncio.create_task(
            app(scope, self._receive, self._send)  # type: ignore[arg-type]
        )

    async def _receive(self) -> dict[str, Any]:
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.start = message
        elif message["type"] == "http.response.body":
            self.chunks.append(message.get("body", b""))
            self.body += message.get("body", b"")

    @property
    def status(self) -> int:
        return int(self.start.get("status", 0))

    @property
    def headers(self) -> dict[str, str]:
        return {k.decode().lower(): v.decode() for k, v in self.start.get("headers", [])}

    async def disconnect(self) -> None:
        self._disconnect.set()
        async with asyncio.timeout(2):
            await self.task


@pytest.fixture
def fast_app(web: Web) -> FastAPI:
    web.app.state.settings = fast_settings(
        PLATFORM_CRM_URL=web.app.state.settings.crm_url,
        PLATFORM_ERP_URL=web.app.state.settings.erp_url,
    )
    return web.app


async def test_stream_requires_a_session(web: Web) -> None:
    response = await web.client.get("/api/v1/events/stream")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


async def test_stream_needs_the_queue_section(web: Web) -> None:
    await web.login([custom(47, "Только счета", {"eds.payments": "read"})])
    response = await web.client.get("/api/v1/events/stream")
    assert response.status_code == 403


async def test_stream_opens_with_sse_headers_and_delivers_a_bus_event(
    web: Web, fast_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_ERP_PLATFORM_BFF", SECRET)
    assert (await web.login(["MANAGER"])).status_code == 200
    web.redis.values["feed:" + web.sid + ":data:erp:/api/v1/notifications/:{}"] = "[]"
    conn = Asgi(fast_app, "/api/v1/events/stream", f"rt_pf_session={web.sid}")
    await until(lambda: conn.status == 200 and b": connected" in conn.body)
    assert conn.headers["content-type"].startswith("text/event-stream")
    assert conn.headers["cache-control"] == "no-cache, no-transform"
    assert conn.headers["x-accel-buffering"] == "no"
    await until(lambda: bool(web.redis.subscribers))

    headers, raw = delivery(envelope("erp", "quote.sent"))
    response = await web.client.post("/bus/v1/events", content=raw, headers=headers)
    assert response.status_code == 200
    await until(lambda: b"event: invalidate" in conn.body)

    data = conn.body.decode().split("data: ", 1)[1].split("\n", 1)[0]
    assert json.loads(data) == {
        "topics": ["notifications", "counters", "queue", "activity"],
        "reason": "uz.railtech.erp.quote.sent.v1",
    }
    assert not any("feed:" in k and ":data:" in k for k in web.redis.values)
    await conn.disconnect()
    assert fast_app.state.hub.streams == 0


async def test_stream_closes_after_logout(web: Web, fast_app: FastAPI) -> None:
    assert (await web.login(["MANAGER"])).status_code == 200
    conn = Asgi(fast_app, "/api/v1/events/stream", f"rt_pf_session={web.sid}")
    await until(lambda: conn.status == 200)
    await web.redis.delete(f"session:{web.sid}")  # выход или истёкший срок
    async with asyncio.timeout(2):
        await conn.task  # BFF сам завершает поток при ближайшем heartbeat
    assert fast_app.state.hub.streams == 0
