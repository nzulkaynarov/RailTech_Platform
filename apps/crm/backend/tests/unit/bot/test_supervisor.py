"""Перезапуск бота на лету: новый токен — новый runtime, диспетчер собирается один раз."""

from typing import Any

import pytest
from aiogram import Dispatcher

from app.bot.supervisor import BotSupervisor
from app.config import Settings
from app.integrations.telegram import TokenSource


class FakeRuntime:
    def __init__(self, token: str) -> None:
        self.token = token
        self.started = False
        self.stopped_with: bool | None = None
        self.bot = self
        self.running = True

    async def start(self) -> None:
        self.started = True

    async def stop(self, *, release_webhook: bool = False) -> None:
        self.stopped_with = release_webhook

    async def get_me(self) -> Any:
        return type("Me", (), {"username": f"bot_{self.token[:3]}"})()


class Harness:
    def __init__(self, mode: str = "polling") -> None:
        self.token: tuple[str, TokenSource] = ("111:first-token", "env")
        self.dispatchers = 0
        self.runtimes: list[FakeRuntime] = []
        self.supervisor = BotSupervisor(
            Settings(_env_file=None, telegram_mode=mode),
            self.resolve,
            self.make_dispatcher,
            self.make_runtime,  # type: ignore[arg-type]
        )

    async def resolve(self) -> tuple[str, TokenSource]:
        return self.token

    async def make_dispatcher(self) -> Dispatcher:
        self.dispatchers += 1
        return Dispatcher()

    def make_runtime(self, config: Settings, dispatcher: Dispatcher, token: str) -> FakeRuntime:
        runtime = FakeRuntime(token)
        self.runtimes.append(runtime)
        return runtime


async def test_restart_switches_token_without_rebuilding_dispatcher() -> None:
    h = Harness()
    await h.supervisor.start()
    assert h.supervisor.running
    assert h.supervisor.username == "bot_111"
    h.token = ("222:second-token", "db")
    await h.supervisor.restart()
    first, second = h.runtimes
    assert first.stopped_with is True
    assert second.token == "222:second-token"
    assert second.started
    assert h.supervisor.source == "db"
    assert h.supervisor.username == "bot_222"
    assert h.dispatchers == 1


async def test_no_token_means_not_running() -> None:
    h = Harness()
    h.token = ("", "none")
    await h.supervisor.start()
    assert not h.supervisor.running
    assert h.runtimes == []
    assert not h.supervisor.secret_matches("anything")


async def test_disabled_mode_never_starts() -> None:
    h = Harness(mode="disabled")
    await h.supervisor.start()
    assert not h.supervisor.running
    assert h.dispatchers == 0


async def test_start_failure_keeps_api_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness()

    async def boom(self: FakeRuntime) -> None:
        raise RuntimeError("telegram down")

    async def close() -> None:
        return None

    monkeypatch.setattr(FakeRuntime, "start", boom)
    monkeypatch.setattr(
        FakeRuntime, "session", type("S", (), {"close": staticmethod(close)})(), raising=False
    )
    await h.supervisor.start()
    assert not h.supervisor.running
    assert h.supervisor.last_error == "RuntimeError"


async def test_finished_polling_task_means_not_running() -> None:
    """Polling-задача завершилась (сеть, отозванный токен) — бот не работает, а не «онлайн»."""
    h = Harness()
    await h.supervisor.start()
    assert h.supervisor.running
    h.runtimes[0].running = False
    assert not h.supervisor.running
