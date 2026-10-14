"""Выключатели в процессе (M3-CRM-12, ADR-0024): кэш, сбой БД, `peek` для Langfuse."""

import asyncio
from typing import Any

from app.integrations import langfuse
from app.services.service_switches import SwitchBoard


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Db:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.reads = 0
        self.broken = False

    def __call__(self) -> "Db":
        return self

    async def __aenter__(self) -> "Db":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def scalars(self, _stmt: Any) -> Any:
        self.reads += 1
        if self.broken:
            raise OSError("db down")
        keys = list(self.keys)
        return type("Result", (), {"all": staticmethod(lambda: keys)})()


async def test_cached_for_ttl_then_reloaded() -> None:
    db, clock = Db(), Clock()
    board = SwitchBoard(db, ttl_s=10, clock=clock)  # type: ignore[arg-type]
    db.keys = ["telegram"]
    assert await board.is_disabled("telegram") is True
    db.keys = []
    assert await board.is_disabled("telegram") is True  # кэш
    clock.now += 11
    assert await board.is_disabled("telegram") is False
    assert db.reads == 2
    board.invalidate()
    db.keys = ["mail"]
    assert await board.disabled_keys() == frozenset({"mail"})


async def test_db_failure_keeps_last_known_state() -> None:
    db, clock = Db(), Clock()
    board = SwitchBoard(db, ttl_s=10, clock=clock)  # type: ignore[arg-type]
    db.keys = ["mail"]
    assert await board.is_disabled("mail")
    db.broken = True
    clock.now += 11
    assert await board.is_disabled("mail") is True


async def test_peek_refreshes_in_background() -> None:
    db, clock = Db(), Clock()
    board = SwitchBoard(db, ttl_s=10, clock=clock)  # type: ignore[arg-type]
    db.keys = ["langfuse"]
    assert board.peek("langfuse") is False  # ещё не знаем — фоновое обновление запущено
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert board.peek("langfuse") is True


def test_langfuse_gate_turns_tracing_off(monkeypatch: Any) -> None:
    sentinel = object()
    monkeypatch.setattr(langfuse, "_client", lambda: sentinel)
    langfuse.set_gate(lambda: False)
    assert langfuse.client() is sentinel
    langfuse.set_gate(lambda: True)
    try:
        assert langfuse.client() is None
    finally:
        langfuse.set_gate(lambda: False)
