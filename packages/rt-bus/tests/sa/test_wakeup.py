"""Пробуждение ретранслятора по коммиту: AsyncBus.wakeup и задача Procrastinate (pg)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus.contrib.procrastinate import install
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import example_data
from .conftest import Hub, rows

pytestmark = pytest.mark.pg

DEAL_WON = "uz.railtech.erp.deal.won.v1"


async def publish(bus: AsyncBus, session: AsyncSession, n: int = 1) -> None:
    for _ in range(n):
        await bus.publish(session, DEAL_WON, example_data("erp/deal.won.v1"))


class Woken:
    def __init__(self) -> None:
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


async def test_wakeup_after_commit_once_per_transaction(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    woken = Woken()
    bus = make_bus()
    bus.wakeup = woken
    async with sessions() as session, session.begin():
        await publish(bus, session, 3)
        await asyncio.sleep(0.05)
        assert woken.count == 0  # до коммита будить рано: строки outbox ещё не видны
    await bus.drain_wakeups()
    assert woken.count == 1  # три publish — одно пробуждение
    async with sessions() as session, session.begin():  # следующая транзакция той же фабрики — своё пробуждение
        await publish(bus, session)
    await bus.drain_wakeups()
    assert woken.count == 2
    assert len(await rows(sessions, "SELECT id FROM rt_bus_outbox")) == 4


async def test_wakeup_reused_session_and_explicit_commit(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    woken = Woken()
    bus = make_bus()
    bus.wakeup = woken
    async with sessions() as session:
        await session.begin()
        await publish(bus, session)
        await session.rollback()
        await bus.drain_wakeups()
        assert woken.count == 0  # откат — пробуждения нет, отметка не переходит в следующую транзакцию
        await session.begin()
        await publish(bus, session)
        await session.commit()
        await bus.drain_wakeups()
        assert woken.count == 1
        await session.begin()
        await session.commit()  # транзакция без publish не будит
        await bus.drain_wakeups()
        assert woken.count == 1


async def test_wakeup_rollback_and_unfinished_session_do_not_wake(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    woken = Woken()
    bus = make_bus()
    bus.wakeup = woken

    async def change_then_fail() -> None:
        async with sessions() as session, session.begin():
            await publish(bus, session)
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError):
        await change_then_fail()
    async with sessions() as session:  # сессию закрыли, не закоммитив
        await session.begin()
        await publish(bus, session)
    await bus.drain_wakeups()
    assert woken.count == 0
    assert await rows(sessions, "SELECT id FROM rt_bus_outbox") == []


async def test_wakeup_savepoint_waits_for_the_outer_commit(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    woken = Woken()
    bus = make_bus()
    bus.wakeup = woken
    async with sessions() as session, session.begin():
        async with session.begin_nested():
            await publish(bus, session)
        await bus.drain_wakeups()
        assert woken.count == 0  # RELEASE SAVEPOINT — это ещё не коммит
        await publish(bus, session)
    await bus.drain_wakeups()
    assert woken.count == 1


async def test_wakeup_failure_does_not_break_commit(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broker_down() -> None:
        raise ConnectionError("broker is down")

    bus = make_bus()
    bus.wakeup = broker_down
    with caplog.at_level(logging.ERROR, logger="rt_bus"):
        async with sessions() as session, session.begin():
            await publish(bus, session)
        await bus.drain_wakeups()
    assert "rt_bus_wakeup_failed" in caplog.text
    assert len(await rows(sessions, "SELECT id FROM rt_bus_outbox")) == 1
    assert (await bus.pump()).relayed == 1  # периодический проход подберёт


async def test_procrastinate_wakeup_delivers_without_waiting_for_the_periodic_pump(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    app = procrastinate.App(connector=InMemoryConnector())
    erp = make_bus("erp")
    tasks = install(app, lambda: erp, pump_cron="0 0 1 1 *")  # периодического прохода «не будет»
    erp.wakeup = tasks.wakeup
    async with app.open_async():
        started = time.monotonic()
        async with sessions() as session, session.begin():
            await publish(erp, session, 2)
        await erp.drain_wakeups()
        jobs = [j["task_name"] for j in app.connector.jobs.values()]  # type: ignore[attr-defined]
        assert jobs == ["rt_bus.pump"]
        async with sessions() as session, session.begin():  # ещё одна транзакция, пока pump ждёт в очереди
            await publish(erp, session)
        await erp.drain_wakeups()
        assert len(app.connector.jobs) == 1  # type: ignore[attr-defined]  # queueing_lock: задачи не копятся
        await app.run_worker_async(wait=False, queues=["rt_bus"])
        elapsed = time.monotonic() - started
    assert {d.status for d in await erp.list_deliveries()} == {"delivered"}
    assert len(hub.to("crm")) == 3
    assert elapsed < 2


async def test_procrastinate_rollback_does_not_defer_pump(
    make_bus: Callable[..., AsyncBus], sessions: async_sessionmaker[AsyncSession]
) -> None:
    app = procrastinate.App(connector=InMemoryConnector())
    erp = make_bus("erp")
    erp.wakeup = install(app, lambda: erp).wakeup
    async with app.open_async():

        async def change_then_fail() -> None:
            async with sessions() as session, session.begin():
                await publish(erp, session)
                raise RuntimeError("business failed")

        with pytest.raises(RuntimeError):
            await change_then_fail()
        await erp.drain_wakeups()
        assert app.connector.jobs == {}  # type: ignore[attr-defined]
