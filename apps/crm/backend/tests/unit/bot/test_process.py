"""Цикл процесса `crm-bot`: старт, запрос на перезапуск из БД, повторные попытки, пульс (S0-4)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.bot.process import BotProcess
from app.config import Settings
from app.services.bot_state import PendingRestart

T1 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
T2 = T1 + timedelta(minutes=5)


class FakeSupervisor:
    def __init__(self) -> None:
        self.running = False
        self.source = "none"
        self.username: str | None = None
        self.last_error: str | None = None
        self.profile = None
        self.calls: list[str] = []
        self.fail_start = False

    async def start(self) -> None:
        self.calls.append("start")
        self._apply()

    async def restart(self) -> None:
        self.calls.append("restart")
        self._apply()

    async def recover(self) -> None:
        self.calls.append("recover")
        self._apply()

    def _apply(self) -> None:
        if self.fail_start:
            self.running, self.last_error = False, "TelegramNetworkError"
        else:
            self.running, self.source, self.username, self.last_error = True, "db", "bot", None


@dataclass
class FakeState:
    pending: PendingRestart = field(default_factory=lambda: PendingRestart(None, None))
    reports: list[dict[str, Any]] = field(default_factory=list)
    applied: list[datetime] = field(default_factory=list)
    broken: bool = False

    async def pending_restart(self) -> PendingRestart:
        if self.broken:
            raise ConnectionError("db down")
        return self.pending

    async def report(self, **kwargs: Any) -> None:
        self.reports.append(kwargs)

    async def mark_applied(self, requested_at: datetime) -> None:
        self.applied.append(requested_at)
        self.pending = PendingRestart(requested_at, requested_at)


class Stamp:
    value: datetime | None = T1

    async def __call__(self) -> datetime | None:
        return self.value


def make(
    sup: FakeSupervisor | None, state: FakeState, stamp: Stamp | None = None, **cfg: Any
) -> BotProcess:
    config = Settings(_env_file=None, telegram_mode="polling", **cfg)
    return BotProcess(config, sup, state, stamp or Stamp())  # type: ignore[arg-type]


async def test_boot_starts_bot_and_reports_with_pulse() -> None:
    sup, state = FakeSupervisor(), FakeState()
    await make(sup, state)._boot()
    assert sup.calls == ["start"]
    assert state.reports[0]["running"] is True
    assert state.reports[0]["started"] is True
    assert state.reports[0]["username"] == "bot"


async def test_boot_treats_old_request_as_applied() -> None:
    """Запрос, пришедший пока процесс лежал, учтён свежим токеном при старте: рестарт не нужен."""
    sup, state = FakeSupervisor(), FakeState(PendingRestart(T1, None))
    process = make(sup, state)
    await process._boot()
    await process._tick()
    assert sup.calls == ["start"]
    assert state.applied == [T1]


async def test_request_from_api_restarts_bot_once() -> None:
    sup, state = FakeSupervisor(), FakeState()
    process = make(sup, state)
    await process._boot()
    state.pending = PendingRestart(T2, T1)
    await process._tick()
    await process._tick()
    assert sup.calls == ["start", "restart"]
    assert state.applied == [T2]


async def test_token_saved_by_other_path_restarts_bot() -> None:
    """Токен сменили не через API (метка `updated_at` изменилась): бот перезапускается сам."""
    sup, state, stamp = FakeSupervisor(), FakeState(), Stamp()
    process = make(sup, state, stamp)
    await process._boot()
    stamp.value = T2
    await process._tick()
    assert sup.calls == ["start", "restart"]
    assert state.applied == []


async def test_failed_start_is_retried_after_pause() -> None:
    sup, state = FakeSupervisor(), FakeState()
    sup.fail_start = True
    process = make(sup, state, bot_retry_s=30.0)
    await process._boot()
    assert state.reports[-1]["running"] is False
    assert state.reports[-1]["last_error"] == "TelegramNetworkError"
    await process._tick()  # пауза ещё не прошла
    assert sup.calls == ["start"]
    sup.fail_start = False
    process._last_attempt -= 31
    await process._tick()
    assert sup.calls == ["start", "recover"]
    assert state.reports[-1]["running"] is True


async def test_status_change_reported_immediately_otherwise_only_pulse() -> None:
    sup, state = FakeSupervisor(), FakeState()
    process = make(sup, state, bot_heartbeat_s=1000.0)
    await process._boot()
    count = len(state.reports)
    await process._tick()
    assert len(state.reports) == count  # ничего не изменилось, пульс ещё не нужен
    sup.running = False
    sup.last_error = "TelegramUnauthorizedError"
    process._last_attempt = float("inf")  # повторную попытку не запускаем — смотрим только отчёт
    await process._tick()
    assert state.reports[-1]["last_error"] == "TelegramUnauthorizedError"
    process._last_report -= 2000
    n = len(state.reports)
    await process._tick()
    assert len(state.reports) == n + 1


async def test_disabled_mode_only_sends_pulse() -> None:
    state = FakeState()
    process = make(None, state)
    await process._boot()
    await process._tick()
    assert state.reports[0]["running"] is False
    assert state.reports[0]["source"] == "none"


async def test_database_outage_does_not_stop_the_loop() -> None:
    sup, state = FakeSupervisor(), FakeState(broken=True)
    process = make(sup, state)
    await process._guard(process._boot)
    await process._guard(process._tick)
    assert process.ticks == 2
    state.broken = False
    await process._guard(process._tick)
    assert state.reports  # цикл жив и снова пишет статус


async def test_disabled_mode_confirms_restart_request() -> None:
    """Без бота (TELEGRAM_MODE=disabled) запрос всё равно подтверждается: API не ждёт 10 с зря."""
    state = FakeState()
    process = make(None, state)
    await process._boot()
    state.pending = PendingRestart(T2, T1)
    await process._tick()
    assert state.applied == [T2]


async def test_failed_restart_is_retried_and_not_confirmed() -> None:
    sup, state = FakeSupervisor(), FakeState()
    process = make(sup, state)
    await process._boot()
    state.pending = PendingRestart(T2, T1)
    broken = True

    async def restart() -> None:
        if broken:
            raise RuntimeError("stop failed")
        sup.calls.append("restart")

    sup.restart = restart  # type: ignore[method-assign]
    await process._guard(process._tick)
    assert state.applied == []
    broken = False
    await process._guard(process._tick)
    assert sup.calls == ["start", "restart"]
    assert state.applied == [T2]


async def test_failed_restart_after_token_change_is_retried() -> None:
    sup, state, stamp = FakeSupervisor(), FakeState(), Stamp()
    process = make(sup, state, stamp)
    await process._boot()
    stamp.value = T2
    broken = True

    async def restart() -> None:
        if broken:
            raise RuntimeError("stop failed")
        sup.calls.append("restart")

    sup.restart = restart  # type: ignore[method-assign]
    await process._guard(process._tick)
    broken = False
    await process._guard(process._tick)
    assert sup.calls == ["start", "restart"]
