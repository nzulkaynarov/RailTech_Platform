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
        self.profile = None
        self.failure: str | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self, *, release_webhook: bool = False) -> None:
        self.stopped_with = release_webhook

    async def get_me(self) -> Any:
        return type("Me", (), {"username": f"bot_{self.token[:3]}"})()


class Harness:
    def __init__(self, mode: str = "polling", url: str = "") -> None:
        self.token: tuple[str, TokenSource] = ("111:first-token", "env")
        self.dispatchers = 0
        self.runtimes: list[FakeRuntime] = []
        self.supervisor = BotSupervisor(
            Settings(_env_file=None, telegram_mode=mode, telegram_webhook_url=url),
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


async def test_webhook_mode_with_empty_url_does_not_start_and_logs_error() -> None:
    """FIX-66: ошибка в журнал (без токена), бот не стартует, runtime даже не создаётся."""
    from structlog.testing import capture_logs

    h = Harness(mode="webhook")
    with capture_logs() as logs:
        await h.supervisor.start()
    assert not h.supervisor.running
    assert h.runtimes == []
    assert h.supervisor.last_error == "webhook_not_configured"
    failed = [e for e in logs if e["event"] == "bot_webhook_not_configured"]
    assert failed
    assert failed[0]["log_level"] == "error"
    assert failed[0]["problem"] == "empty"
    assert "111:first-token" not in repr(logs)
    assert not any(e["event"] == "bot_started" for e in logs)


async def test_webhook_mode_with_http_url_does_not_start() -> None:
    h = Harness(mode="webhook", url="http://crm.example/telegram/webhook")
    await h.supervisor.start()
    assert h.runtimes == []
    assert h.supervisor.last_error == "webhook_not_configured"


async def test_webhook_mode_with_https_url_starts() -> None:
    h = Harness(mode="webhook", url="https://crm.example/telegram/webhook")
    await h.supervisor.start()
    assert h.supervisor.running
    assert h.supervisor.last_error is None


# --- S0-4: crm-bot сам поднимает бота, если старт не удался или polling упал -------------------


async def test_recover_after_failed_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telegram был недоступен при старте процесса: следующая попытка поднимает бота."""
    h = Harness()
    attempts = 0

    async def flaky(self: FakeRuntime) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("telegram down")
        self.started = True

    async def close() -> None:
        return None

    monkeypatch.setattr(FakeRuntime, "start", flaky)
    monkeypatch.setattr(
        FakeRuntime, "session", type("S", (), {"close": staticmethod(close)})(), raising=False
    )
    await h.supervisor.start()
    assert not h.supervisor.running
    await h.supervisor.recover()
    assert h.supervisor.running
    assert h.supervisor.last_error is None
    assert h.dispatchers == 1


async def test_recover_replaces_dead_polling_and_keeps_its_error() -> None:
    h = Harness()
    await h.supervisor.start()
    dead = h.runtimes[0]
    dead.running = False
    dead.failure = "TelegramUnauthorizedError"
    await h.supervisor.recover()
    assert dead.stopped_with is False  # вебхук не трогаем
    assert len(h.runtimes) == 2
    assert h.supervisor.running


async def test_recover_does_nothing_when_running() -> None:
    h = Harness()
    await h.supervisor.start()
    await h.supervisor.recover()
    assert len(h.runtimes) == 1


async def test_recover_without_token_is_quiet() -> None:
    from structlog.testing import capture_logs

    h = Harness()
    h.token = ("", "none")
    with capture_logs() as logs:
        await h.supervisor.recover()
    assert h.runtimes == []
    assert not [e for e in logs if e["log_level"] in ("warning", "error")]
