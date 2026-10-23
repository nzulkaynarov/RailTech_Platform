"""Тестовые двойники: Redis в памяти (только используемые BFF команды) и управляемые часы."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.session import RELEASE_LOCK


class Clock:
    """Часы тестов: подменяют `app.session.now` и `app.auth.now`, общие с FakeRedis."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakePubSub:
    """Подписка pub/sub в памяти: `get_message` ждёт сообщение до `timeout` секунд (настоящих)."""

    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.channels: set[str] = set()

    async def subscribe(self, *channels: str) -> None:
        if self.redis.pubsub_down:
            raise ConnectionError("redis down")
        self.channels.update(channels)
        self.redis.subscribers.append(self)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = False,
        timeout: float = 0.0,  # noqa: ASYNC109
    ) -> dict[str, Any] | None:
        if self.redis.pubsub_down:
            raise ConnectionError("redis down")
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        if self in self.redis.subscribers:
            self.redis.subscribers.remove(self)


class FakeRedis:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.values: dict[str, str] = {}
        self.expires: dict[str, float] = {}
        self.subscribers: list[FakePubSub] = []
        self.pubsub_down = False
        self.published: list[tuple[str, str]] = []

    def _alive(self, key: str) -> bool:
        deadline = self.expires.get(key)
        if deadline is not None and deadline <= self.clock.t:
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return key in self.values

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.values[key] if self._alive(key) else None

    async def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and self._alive(key):
            return None
        self.values[key] = str(value)
        self.expires.pop(key, None)
        if ex is not None:
            self.expires[key] = self.clock.t + ex
        if px is not None:
            self.expires[key] = self.clock.t + px / 1000
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self._alive(key):
                removed += 1
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        value = int(self.values[key]) + 1 if self._alive(key) else 1
        self.values[key] = str(value)
        return value

    async def ttl(self, key: str) -> int:
        if not self._alive(key):
            return -2
        deadline = self.expires.get(key)
        return -1 if deadline is None else max(int(deadline - self.clock.t), 0)

    async def expire(self, key: str, seconds: int) -> bool:
        if not self._alive(key):
            return False
        self.expires[key] = self.clock.t + seconds
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        assert script == RELEASE_LOCK
        key, token = args[0], args[1]
        if self._alive(key) and self.values[key] == token:
            return await self.delete(key)
        return 0

    async def aclose(self) -> None:
        return None

    async def publish(self, channel: str, message: str) -> int:
        if self.pubsub_down:
            raise ConnectionError("redis down")
        self.published.append((channel, message))
        receivers = [sub for sub in self.subscribers if channel in sub.channels]
        for sub in receivers:
            sub.queue.put_nowait({"type": "message", "channel": channel, "data": message})
        return len(receivers)

    def pubsub(self) -> FakePubSub:
        return FakePubSub(self)

    async def scan_iter(self, match: str, count: int = 10) -> AsyncIterator[str]:
        prefix = match.removesuffix("*")
        for key in list(self.values):
            if key.startswith(prefix) and self._alive(key):
                yield key

    # --- помощники тестов ---
    def session_keys(self) -> list[str]:
        return [k for k in list(self.values) if k.startswith("session:") and self._alive(k)]

    def read_session(self, sid: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.values[f"session:{sid}"])
        return loaded

    def write_session(self, sid: str, data: dict[str, Any]) -> None:
        self.values[f"session:{sid}"] = json.dumps(data)
