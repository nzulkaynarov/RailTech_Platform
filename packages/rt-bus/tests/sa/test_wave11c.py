"""Волна 11c (F1) на настоящем PostgreSQL: взаимная блокировка pump (W11B-G-1), `enabled: false` не теряет события
(W11B-G-2), догон после восстановления подписчика (C1-G-6), метрики выключенного подписчика."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from rt_bus import BreakerPolicy, sql
from rt_bus.core import retryable_db_error
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import Clock, example_data
from .conftest import Hub, rows

pytestmark = pytest.mark.pg

QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"
PENDING_ALL = "SELECT id, attempts, next_attempt_at FROM rt_bus_delivery WHERE subscriber = 'crm' ORDER BY id"
PENDING_CRM = "SELECT next_attempt_at, status FROM rt_bus_delivery WHERE status = 'pending' AND subscriber = 'crm'"


async def publish(bus: AsyncBus, sessions: async_sessionmaker[AsyncSession], n: int = 1) -> list[str]:
    """`n` событий `quote.sent` (получатели crm и audit), уже разложенных ретранслятором."""
    async with sessions() as session, session.begin():
        ids = [(await bus.publish(session, QUOTE_SENT, example_data("erp/quote.sent.v1"))).id for _ in range(n)]
    await bus.relay()
    return ids


def edit_subscriber(path: Path, name: str, **fields: Any) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in raw["subscribers"]:
        if item["name"] == name:
            item.update(fields)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


# --- W11B-G-1: два pump с новым подписчиком не блокируют друг друга ---------------------------------------------


async def test_parallel_pumps_with_new_subscribers_do_not_deadlock(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    engine: AsyncEngine,
    clock: Clock,
) -> None:
    """Периодический pump и пробуждение берут по доставке crm и audit в разном порядке; строки состояния обоих
    подписчиков новые. Раньше итоги писались в порядке пачки в одной транзакции — `DeadlockDetected`, аренда на 60 с."""
    first, second = make_bus(delivery_batch=2), make_bus(delivery_batch=2)
    for round_no in range(30):
        async with engine.begin() as conn:
            await conn.execute(
                text("TRUNCATE rt_bus_outbox, rt_bus_delivery, rt_bus_subscriber_state RESTART IDENTITY CASCADE")
            )
        await publish(first, sessions, n=2)
        # порядок выдачи: crm, audit, audit, crm — обеим пачкам достаётся разный порядок подписчиков
        async with engine.begin() as conn:
            for position, (event_index, subscriber) in enumerate([(0, "crm"), (0, "audit"), (1, "audit"), (1, "crm")]):
                await conn.execute(
                    text(
                        "UPDATE rt_bus_delivery "
                        "SET next_attempt_at = CAST(:base AS timestamptz) - make_interval(secs => :age) "
                        "WHERE subscriber = :s AND event_id = (SELECT id FROM rt_bus_outbox ORDER BY created_at, id "
                        "OFFSET :i LIMIT 1)"
                    ),
                    {"base": clock(), "age": 100 - position, "s": subscriber, "i": event_index},
                )
        gate = asyncio.Barrier(4)

        async def meet(request: httpx.Request, gate: asyncio.Barrier = gate) -> httpx.Response:
            try:
                async with asyncio.timeout(3):
                    await gate.wait()  # все четыре ответа уходят одновременно: итоги пишутся внахлёст
            except (TimeoutError, asyncio.BrokenBarrierError):
                pass
            return httpx.Response(200)

        hub.responders["crm"] = hub.responders["audit"] = meet
        stats = await asyncio.wait_for(asyncio.gather(first.pump(), second.pump()), timeout=30)
        assert sum(s.deliver.delivered for s in stats) == 4, round_no
        assert sum(s.deliver.lost_lease for s in stats) == 0
        statuses = await rows(sessions, "SELECT subscriber, status FROM rt_bus_delivery")
        assert (
            sorted((r["subscriber"], r["status"]) for r in statuses)
            == [("audit", "delivered")] * 2 + [("crm", "delivered")] * 2
        ), round_no
        states = await rows(sessions, "SELECT subscriber, consecutive_failures FROM rt_bus_subscriber_state")
        assert {r["subscriber"] for r in states} == {"crm", "audit"}


async def test_deadlock_in_record_is_retried_and_does_not_hold_other_subscribers(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Запись итогов подписчика упала на 40P01 — группа повторяется, прочие подписчики записаны с первого раза."""
    from rt_bus.sqlalchemy import bus as module

    class DeadlockError(Exception):
        sqlstate = "40P01"

    bus = make_bus(delivery_batch=10)
    await publish(bus, sessions, n=2)
    real = module._exec
    failed: list[str] = []

    async def flaky(session: AsyncSession, statement: str, params: Any = None) -> Any:
        if statement == sql.BREAKER_SUCCESS and params and params["subscriber"] == "audit" and not failed:
            failed.append("audit")
            raise DeadlockError("deadlock detected")
        return await real(session, statement, params)

    monkeypatch.setattr(module, "_exec", flaky)
    stats = await bus.deliver()
    assert failed == ["audit"]
    assert stats.delivered == 4
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery")} == {"delivered"}


async def test_other_error_in_record_leaves_other_subscribers_recorded(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неповторяемая ошибка записи одной группы: остальные записаны, аренда чужих не висит, ошибка поднимается."""
    from rt_bus.sqlalchemy import bus as module

    bus = make_bus(delivery_batch=10)
    await publish(bus, sessions, n=2)
    real = module._exec

    async def broken(session: AsyncSession, statement: str, params: Any = None) -> Any:
        if statement == sql.BREAKER_SUCCESS and params and params["subscriber"] == "audit":
            raise RuntimeError("boom")
        return await real(session, statement, params)

    monkeypatch.setattr(module, "_exec", broken)
    with pytest.raises(RuntimeError, match="boom"):
        await bus.deliver()
    by_subscriber = {
        (r["subscriber"], r["status"]) for r in await rows(sessions, "SELECT subscriber, status FROM rt_bus_delivery")
    }
    assert by_subscriber == {("crm", "delivered"), ("audit", "in_flight")}


def test_retryable_db_error_walks_the_chain() -> None:
    class DriverError(Exception):
        sqlstate = "40P01"

    class WrapperError(Exception):
        def __init__(self, orig: BaseException) -> None:
            super().__init__("wrapped")
            self.orig = orig

    outer = RuntimeError("outer")
    outer.__cause__ = DriverError()
    assert retryable_db_error(WrapperError(DriverError()))
    assert retryable_db_error(outer)
    assert not retryable_db_error(RuntimeError("other"))


# --- W11B-G-2: enabled: false копит доставки, drop: true — нет ----------------------------------------------------


async def test_disabled_subscriber_accumulates_and_delivers_in_order_after_enable(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    subscriptions_file: Path,
    clock: Clock,
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False)  # drop по умолчанию false
    ids: list[str] = []
    for _ in range(3):  # опубликованы и разложены, пока crm выключен
        ids += await publish(bus, sessions)
        clock.advance(1)
    held = await rows(sessions, "SELECT event_id, status, attempts FROM rt_bus_delivery WHERE subscriber = 'crm'")
    assert sorted(str(r["event_id"]) for r in held) == sorted(ids)
    assert {(r["status"], r["attempts"]) for r in held} == {("pending", 0)}

    stats = await bus.pump()
    assert stats.deliver.delivered == 3  # audit; crm не отправляется
    assert hub.to("crm") == []
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery WHERE subscriber='crm'")} == {
        "pending"
    }

    edit_subscriber(subscriptions_file, "crm", enabled=True)
    stats = await bus.pump()
    assert stats.deliver.delivered == 3
    sent = [r.headers["x-rt-event-id"] for r in hub.to("crm")]
    assert sent == ids  # по порядку публикации
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery")} == {"delivered"}


async def test_disabled_subscriber_with_drop_gets_no_rows(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    subscriptions_file: Path,
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False, drop=True)
    await publish(bus, sessions, n=2)
    assert await rows(sessions, "SELECT id FROM rt_bus_delivery WHERE subscriber = 'crm'") == []
    edit_subscriber(subscriptions_file, "crm", enabled=True)
    await publish(bus, sessions, n=1)  # после включения подписчик снова получает новое
    await bus.pump()
    assert len(hub.to("crm")) == 1


async def test_disabled_subscriber_does_not_raise_oldest_age_alert(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    subscriptions_file: Path,
    clock: Clock,
) -> None:
    bus = make_bus()
    edit_subscriber(subscriptions_file, "crm", enabled=False)
    await publish(bus, sessions, n=2)
    await bus.pump()
    clock.advance(2 * 3600)  # дольше часа: ожидающие у выключенного — не авария
    metrics = await bus.metrics()
    crm = metrics.subscribers["crm"]
    assert (crm.enabled, crm.pending) == (False, 2)
    assert crm.oldest_undelivered_age_seconds is not None
    assert crm.oldest_undelivered_age_seconds >= 2 * 3600
    assert metrics.oldest_undelivered_age_seconds is None  # общий возраст — только включённые

    edit_subscriber(subscriptions_file, "crm", enabled=True)
    metrics = await bus.metrics()
    assert metrics.subscribers["crm"].enabled
    assert metrics.oldest_undelivered_age_seconds is not None
    assert metrics.oldest_undelivered_age_seconds >= 2 * 3600


# --- C1-G-6: накопленные доставки уходят сразу после восстановления ------------------------------------------------


async def test_recovered_subscriber_gets_backlog_immediately(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
) -> None:
    bus = make_bus(delivery_batch=2)
    await publish(bus, sessions, n=6)
    hub.responders["crm"] = lambda r: httpx.Response(503)
    await bus.pump()  # все 6 доставок crm — первая неудача, предохранитель открыт
    async with sessions() as session, session.begin():
        # остальные ждут далеко: так выглядят повторы после долгого простоя (10 мин, 1 ч, …)
        await session.execute(
            text(
                "UPDATE rt_bus_delivery SET next_attempt_at = :far WHERE subscriber = 'crm' AND id <> "
                "(SELECT min(id) FROM rt_bus_delivery WHERE subscriber = 'crm')"
            ),
            {"far": clock() + timedelta(hours=2)},
        )
    clock.advance(301)  # пауза кончилась; ближайшая готовая доставка — проба
    hub.responders.pop("crm")
    before = len(hub.to("crm"))

    stats = await bus.pump()
    assert stats.deliver.recovered == 1
    assert len(hub.to("crm")) - before == 6  # проба и 5 накопленных, пачками по 2, а не по расписанию (+2 ч)
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery")} == {"delivered"}
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert (state["consecutive_failures"], state["paused_until"]) == (0, None)


async def test_recovery_needs_open_breaker_to_reset_schedules(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
) -> None:
    """Одиночная ошибка (ниже порога) расписание чужих повторов не трогает: «ядовитое» событие не выжигает попытки."""
    bus = make_bus(breaker=BreakerPolicy(threshold=5))
    ids = await publish(bus, sessions, n=2)
    hub.responders["crm"] = lambda r: httpx.Response(503 if r.headers["x-rt-event-id"] == ids[0] else 200)
    await bus.pump()  # ids[0]: 503, ids[1]: 200
    [poison] = await rows(sessions, PENDING_CRM)
    assert poison["next_attempt_at"] > clock()
    hub.responders.pop("crm")
    await publish(bus, sessions, n=1)
    stats = await bus.pump()
    assert stats.deliver.recovered == 0
    [still] = await rows(sessions, PENDING_CRM)
    assert still["next_attempt_at"] == poison["next_attempt_at"]


async def _open_breaker_with_far_schedule(
    bus: AsyncBus, sessions: async_sessionmaker[AsyncSession], hub: Hub, clock: Clock
) -> None:
    """crm упал (предохранитель открыт), а срок повтора у всех его доставок далеко — тихий период без нового трафика."""
    await publish(bus, sessions, n=3)
    hub.responders["crm"] = lambda r: httpx.Response(503)
    await bus.pump()
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE rt_bus_delivery SET next_attempt_at = :far WHERE subscriber = 'crm'"),
            {"far": clock() + timedelta(hours=2)},
        )


async def test_quiet_period_probe_goes_by_pause_not_by_delivery_schedule(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
) -> None:
    """Без нового трафика проба идёт по сроку паузы предохранителя: восстановление не ждёт расписания повторов."""
    bus = make_bus(breaker=BreakerPolicy(threshold=2))
    await _open_breaker_with_far_schedule(bus, sessions, hub, clock)
    clock.advance(301)  # пауза кончилась, все доставки crm по расписанию ещё не готовы
    hub.responders.pop("crm")
    stats = await bus.pump()
    assert stats.deliver.recovered == 1
    assert {r["status"] for r in await rows(sessions, "SELECT status FROM rt_bus_delivery")} == {"delivered"}


async def test_failed_early_probe_keeps_schedule_and_attempts(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    clock: Clock,
) -> None:
    """Неудача пробы, взявшей доставку раньше срока: пауза продлена, а срок и число попыток доставки прежние."""
    bus = make_bus(breaker=BreakerPolicy(threshold=2))
    await _open_breaker_with_far_schedule(bus, sessions, hub, clock)
    before = {r["id"]: (r["attempts"], r["next_attempt_at"]) for r in await rows(sessions, PENDING_ALL)}
    clock.advance(301)
    stats = await bus.pump()  # crm по-прежнему отвечает 503
    assert stats.deliver.postponed == 1
    after = {r["id"]: (r["attempts"], r["next_attempt_at"]) for r in await rows(sessions, PENDING_ALL)}
    assert after == before
    [state] = await rows(sessions, "SELECT * FROM rt_bus_subscriber_state WHERE subscriber = 'crm'")
    assert state["consecutive_failures"] == 4
    assert state["paused_until"] == clock() + timedelta(seconds=300)
    assert (await bus.pump()).deliver.claimed == 0  # пауза: следующая проба через 5 мин, а не сразу
