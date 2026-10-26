"""Пробуждение ретранслятора rt_bus по коммиту в CRM (B5a, `docs/architecture/rt-bus.md` §4 и §7).

Сервис CRM публикует событие в транзакции изменения; после её коммита шина ставит задачу
`rt_bus.pump` в очередь Procrastinate (на месте — `InMemoryConnector`), и воркер сразу раскладывает
outbox и доставляет подписчику: не ждёт периодический проход (тик в 5 с). Откат — пробуждения нет;
сбой очереди не ломает изменение; пока `pump` ждёт в очереди, новые не ставятся (`queueing_lock`).
"""

import logging
import time
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from procrastinate import testing
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.bus.runtime import CrmBus, build_bus
from app.models.clients import Client
from app.security.principal import Principal
from app.services.clients import ClientService
from app.tasks import bus as bus_tasks
from app.tasks.queue import queue
from tests.bus_events import WEBHOOK_SECRET
from tests.integration.crm_helpers import make_user
from tests.integration.test_bus_publish import clear_outbox

pytestmark = pytest.mark.integration


@pytest.fixture
def connector() -> Iterator[testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        yield connector


@pytest.fixture
def sent() -> list[httpx.Request]:
    """Запросы, дошедшие до подписчика ERP."""
    return []


@pytest.fixture
async def stand(
    sessions: async_sessionmaker[AsyncSession],
    connector: testing.InMemoryConnector,
    monkeypatch: pytest.MonkeyPatch,
    sent: list[httpx.Request],
) -> AsyncIterator[CrmBus]:
    """Шина с пробуждением (как `Container.bus`); ERP отвечает 200, запросы копятся в `sent`."""
    bus = build_bus(sessions, None, wakeup=bus_tasks.tasks.wakeup)
    bus.secret_cache.set_webhook_secrets([WEBHOOK_SECRET])

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"status": "received"})

    bus._http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    runtime.set_bus(bus)
    monkeypatch.setattr(bus_tasks, "get_container", lambda: SimpleNamespace(bus=bus))
    yield bus
    runtime.set_bus(None)
    await bus.aclose()


async def admin(sessions: async_sessionmaker[AsyncSession]) -> Principal:
    account, _ = await make_user(sessions, "wake-admin@railtech.uz", ["admin"])
    await clear_outbox(sessions)
    return Principal(user_id=account.id, full_name="Админ Админов", roles=("admin",))


async def run_pump_worker() -> None:
    async with queue.open_async():
        await queue.run_worker_async(wait=False, queues=["rt_bus"])


async def test_commit_starts_delivery_without_waiting_for_the_periodic_pump(
    sessions: async_sessionmaker[AsyncSession],
    stand: CrmBus,
    connector: testing.InMemoryConnector,
    sent: list[httpx.Request],
) -> None:
    who = await admin(sessions)
    clients = ClientService(sessions)
    client_id = await clients.create(who, "ООО Пробуждение", None, None)
    connector.jobs.clear()  # пробуждения создания клиента нас не интересуют

    started = time.monotonic()
    await clients.update(who, client_id, {"inn": "300000777"})  # client.updated → подписчик erp
    await stand.drain_wakeups()
    assert [job["task_name"] for job in connector.jobs.values()] == ["rt_bus.pump"]
    assert sent == []  # воркер ещё не взял задачу, периодического прохода не ждём

    await run_pump_worker()
    elapsed = time.monotonic() - started
    assert [r.url.host for r in sent] == ["erp-backend"]
    async with sessions() as session:
        statuses = (
            (await session.execute(text("SELECT status FROM rt_bus_delivery"))).scalars().all()
        )
    assert list(statuses) == ["delivered"]
    assert elapsed < 2, f"commit-to-delivery took {elapsed:.2f} s"


async def test_many_publishes_in_one_transaction_and_many_commits_queue_one_pump(
    sessions: async_sessionmaker[AsyncSession],
    stand: CrmBus,
    connector: testing.InMemoryConnector,
) -> None:
    who = await admin(sessions)
    connector.jobs.clear()
    async with sessions() as session, session.begin():
        for name in ("А", "Б", "В"):
            client = Client(name=name, owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            await bus_events.client_created(session, client, who.actor)
        await stand.drain_wakeups()
        assert connector.jobs == {}  # до коммита задачи нет
        client_id = client.id
    await stand.drain_wakeups()
    # второй коммит, пока pump ещё ждёт в очереди: задачи не копятся (queueing_lock)
    await ClientService(sessions).update(who, client_id, {"inn": "300000779"})
    await stand.drain_wakeups()
    assert [job["task_name"] for job in connector.jobs.values()] == ["rt_bus.pump"]


async def test_a_rolled_back_change_does_not_wake_the_pump(
    sessions: async_sessionmaker[AsyncSession],
    stand: CrmBus,
    connector: testing.InMemoryConnector,
) -> None:
    who = await admin(sessions)
    connector.jobs.clear()

    async def change_and_fail() -> None:
        async with sessions() as session, session.begin():
            client = Client(name="Откатится", owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            await bus_events.client_created(session, client, who.actor)
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError):
        await change_and_fail()
    await stand.drain_wakeups()
    assert connector.jobs == {}


async def test_a_queue_failure_does_not_break_the_change_and_the_periodic_pump_delivers(
    sessions: async_sessionmaker[AsyncSession],
    stand: CrmBus,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def queue_down(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("queue is down")

    who = await admin(sessions)
    monkeypatch.setattr(stand, "wakeup", queue_down)
    clients = ClientService(sessions)
    with caplog.at_level(logging.ERROR, logger="rt_bus"):
        client_id = await clients.create(who, "ООО Очередь", None, None)
        await clients.update(who, client_id, {"inn": "300000778"})
        await stand.drain_wakeups()
    assert "rt_bus_wakeup_failed" in caplog.text
    # событие на месте, периодический проход подберёт
    assert (await stand.pump()).deliver.delivered == 1
