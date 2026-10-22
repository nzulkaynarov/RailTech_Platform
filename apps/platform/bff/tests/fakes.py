"""Тестовые двойники: Redis в памяти (только используемые BFF команды) и управляемые часы."""

import json
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


class FakeRedis:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.values: dict[str, str] = {}
        self.expires: dict[str, float] = {}

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

    # --- помощники тестов ---
    def session_keys(self) -> list[str]:
        return [k for k in list(self.values) if k.startswith("session:") and self._alive(k)]

    def read_session(self, sid: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.values[f"session:{sid}"])
        return loaded

    def write_session(self, sid: str, data: dict[str, Any]) -> None:
        self.values[f"session:{sid}"] = json.dumps(data)
