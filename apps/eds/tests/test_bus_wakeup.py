"""Пробуждение ретранслятора rt_bus по коммиту в EDS (B5a, `docs/architecture/rt-bus.md` §4 и §7; находка C1-G-2).

Сервис публикует событие в транзакции изменения; после её коммита шина ставит задачу `rt_bus.pump` в очередь
Procrastinate (в тестах — `InMemoryConnector`), и воркер раскладывает outbox сразу, не ждёт тик в 5 с. Откат —
пробуждения нет; одна транзакция — одно пробуждение; сбой очереди не ломает изменение.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from procrastinate import testing
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.runtime import build_bus
from app.config import Settings
from app.container import Container
from app.schemas.letters import LetterCreate
from app.services import letters
from app.tasks import bus as bus_tasks
from app.tasks.queue import queue
from tests.domain import Person, outbox
from tests.test_letters import NEW_LETTER


@pytest.fixture
def connector() -> Iterator[testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        yield connector


@pytest.fixture
async def stand(container: Container, connector: testing.InMemoryConnector) -> AsyncIterator[AsyncBus]:
    """Шина с пробуждением (как `Container.bus` вне тестов) на базе тестового контейнера."""
    bus = build_bus(container.session_factory, wakeup=bus_tasks.tasks.wakeup)
    yield bus
    await bus.aclose()


def pump_jobs(connector: testing.InMemoryConnector) -> list[str]:
    return [job["task_name"] for job in connector.jobs.values()]


async def register_letter(session: AsyncSession, bus: AsyncBus, request_id: int = 77) -> None:
    """Регистрация письма — публикует `letter.registered`; письмо на заявку одно, поэтому номер заявки разный."""
    links = {**NEW_LETTER["links"], "erp_request_id": request_id}
    await letters.register(session, bus, actor_id=4, data=LetterCreate.model_validate({**NEW_LETTER, "links": links}))


@pytest.mark.pg
async def test_commit_wakes_the_pump_once(
    container: Container, stand: AsyncBus, connector: testing.InMemoryConnector, staff: dict[str, Person]
) -> None:
    async with container.session_factory() as session, session.begin():
        await register_letter(session, stand)
        await stand.drain_wakeups()
        assert connector.jobs == {}  # до коммита задачи нет
    await stand.drain_wakeups()

    assert len(await outbox(container, "letter.registered")) == 1
    (job,) = connector.jobs.values()
    assert (job["task_name"], job["queue_name"], job["queueing_lock"]) == (
        "rt_bus.pump",
        "rt_bus",
        "rt_bus.pump.wakeup",
    )


@pytest.mark.pg
async def test_many_publishes_in_one_transaction_and_many_commits_queue_one_pump(
    container: Container, stand: AsyncBus, connector: testing.InMemoryConnector, staff: dict[str, Person]
) -> None:
    async with container.session_factory() as session, session.begin():
        for request_id in (1, 2, 3):
            await register_letter(session, stand, request_id)
    await stand.drain_wakeups()
    assert pump_jobs(connector) == ["rt_bus.pump"]

    # второй коммит, пока pump ещё ждёт в очереди: задачи не копятся (queueing_lock)
    async with container.session_factory() as session, session.begin():
        await register_letter(session, stand, 4)
    await stand.drain_wakeups()
    assert pump_jobs(connector) == ["rt_bus.pump"]
    assert len(await outbox(container, "letter.registered")) == 4


@pytest.mark.pg
async def test_a_rolled_back_change_does_not_wake_the_pump(
    container: Container, stand: AsyncBus, connector: testing.InMemoryConnector, staff: dict[str, Person]
) -> None:
    async def change_and_fail() -> None:
        async with container.session_factory() as session, session.begin():
            await register_letter(session, stand)
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError):
        await change_and_fail()
    await stand.drain_wakeups()

    assert connector.jobs == {}
    assert await outbox(container) == []


@pytest.mark.pg
async def test_a_queue_failure_does_not_break_the_change(
    container: Container,
    stand: AsyncBus,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    staff: dict[str, Person],
) -> None:
    async def queue_down(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("queue is down")

    monkeypatch.setattr(stand, "wakeup", queue_down)
    with caplog.at_level(logging.ERROR, logger="rt_bus"):
        async with container.session_factory() as session, session.begin():
            await register_letter(session, stand)
        await stand.drain_wakeups()

    assert "rt_bus_wakeup_failed" in caplog.text
    assert len(await outbox(container, "letter.registered")) == 1  # событие на месте, периодический pump подберёт


async def test_the_wakeup_task_defers_one_pump_to_the_bus_queue(connector: testing.InMemoryConnector) -> None:
    await bus_tasks.tasks.wakeup()
    await bus_tasks.tasks.wakeup()

    (job,) = connector.jobs.values()
    assert (job["task_name"], job["queue_name"], job["queueing_lock"]) == (
        "rt_bus.pump",
        "rt_bus",
        "rt_bus.pump.wakeup",
    )


def container_settings(app_env: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env=app_env,
        EDS_DATABASE_URL="postgresql://x/y",
        EDS_ACCESS_SECRET="a" * 40,
        PLATFORM_SSO_SECRET="s" * 40,
    )


def test_the_container_bus_wakes_the_pump_after_commit_outside_tests() -> None:
    bus = Container(container_settings("dev")).bus
    assert bus.wakeup == bus_tasks.tasks.wakeup
    assert bus.enqueue == bus_tasks.tasks.enqueue


def test_the_test_container_bus_has_no_queue() -> None:
    bus = Container(container_settings("test")).bus
    assert (bus.wakeup, bus.enqueue) == (None, None)


async def test_drain_bus_waits_for_pending_wakeups_only_when_the_bus_exists(
    connector: testing.InMemoryConnector,
) -> None:
    container = Container(container_settings("dev"))
    await container.drain_bus()  # шины нет — ничего не создаётся
    assert "bus" not in container.__dict__

    task = asyncio.create_task(bus_tasks.tasks.wakeup())
    container.bus._wake_tasks.add(task)
    await container.drain_bus()
    assert task.done()
    assert pump_jobs(connector) == ["rt_bus.pump"]


async def test_the_worker_polls_the_queue_every_second(
    connector: testing.InMemoryConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W11B-G-6: воркер EDS опрашивает очередь раз в секунду (`WORKER_OPTIONS`), как воркер CRM."""
    from app.__main__ import _run_worker

    seen: dict[str, Any] = {}

    async def fake_run_worker(**kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(queue, "run_worker_async", fake_run_worker)
    await _run_worker()
    assert seen["fetch_job_polling_interval"] <= 1.0
    assert seen["delete_jobs"] == "successful"
