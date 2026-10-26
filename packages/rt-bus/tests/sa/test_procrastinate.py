"""Задачи Procrastinate (CRM): регистрация, периодические задачи, постановка обработки inbox в очередь."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession

from rt_bus import Event, HandlerRegistry
from rt_bus.contrib.procrastinate import PUMP_LOCK, WAKEUP_LOCK, WORKER_OPTIONS, install
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import example, example_data, signed

pytestmark = pytest.mark.pg


async def test_procrastinate_tasks(make_bus: Callable[..., AsyncBus], sessions) -> None:  # type: ignore[no-untyped-def]
    app = procrastinate.App(connector=InMemoryConnector())
    registry = HandlerRegistry()
    handled: list[str] = []

    @registry.subscribe("uz.railtech.erp.quote.sent.v1")
    async def on_quote(event: Event, session: AsyncSession) -> None:
        handled.append(event.id)

    crm = make_bus("crm", registry=registry)
    erp = make_bus("erp")
    tasks = install(app, lambda: crm, pump_cron="* * * * * */2")
    assert {
        "rt_bus.pump",
        "rt_bus.process_inbox",
        "rt_bus.requeue_stuck_inbox",
        "rt_bus.log_metrics",
        "rt_bus.purge",
    } <= set(app.tasks)
    periodic = {p.task.name: p.cron for p in app.periodic_registry.periodic_tasks.values()}
    assert periodic["rt_bus.pump"] == "* * * * * */2"
    crm.enqueue = tasks.enqueue

    env = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
    headers, body = signed(env)
    async with app.open_async():
        assert (await crm.receive(headers, body)).body["status"] == "received"
        jobs = list(app.connector.jobs.values())  # type: ignore[attr-defined]
        assert [(j["task_name"], j["args"]) for j in jobs] == [("rt_bus.process_inbox", {"event_id": env["id"]})]
        await app.run_worker_async(wait=False, queues=["rt_bus"])
    assert handled == [env["id"]]

    # pump у издателя — та же функция, что и вызывается периодической задачей
    async with sessions() as session, session.begin():
        await erp.publish(session, "uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
    stats = await erp.pump()
    assert (stats.relayed, stats.deliver.delivered) == (1, 1)


class _CountingBus:
    """Вместо AsyncBus: считает запуски `pump` (тело задачи)."""

    def __init__(self) -> None:
        self.started: list[float] = []

    async def pump(self) -> None:
        self.started.append(time.monotonic())

    async def requeue_stuck_inbox(self) -> int:
        return 0

    async def log_metrics(self) -> None:
        return None

    async def purge(self, older_than: object) -> None:
        return None


async def test_wakeup_does_not_merge_with_periodic_pump_scheduled_later() -> None:
    """W11B-G-6: периодический `pump` поставлен и ещё не стартует (запланирован позже) — пробуждение его не ждёт."""
    app = procrastinate.App(connector=InMemoryConnector())
    bus = _CountingBus()
    tasks = install(app, lambda: bus, pump_cron="0 0 1 1 *")  # type: ignore[arg-type, return-value]
    async with app.open_async():
        await tasks.pump.configure(schedule_in={"seconds": 30}).defer_async(timestamp=1)  # как тик cron, но позже
        asked = time.monotonic()
        await tasks.wakeup()
        jobs = list(app.connector.jobs.values())  # type: ignore[attr-defined]
        assert sorted(j["queueing_lock"] for j in jobs) == [PUMP_LOCK, WAKEUP_LOCK]  # две задачи, не слияние
        await app.run_worker_async(wait=False, queues=["rt_bus"], **WORKER_OPTIONS)
    assert len(bus.started) == 1  # стартовало пробуждение; периодический ждёт своего срока
    assert bus.started[0] - asked <= 1.0


async def test_wakeups_merge_with_each_other_only() -> None:
    """Ожидающее пробуждение ещё не начало раскладку и заберёт новое событие: второе пробуждение — `AlreadyEnqueued`."""
    app = procrastinate.App(connector=InMemoryConnector())
    bus = _CountingBus()
    tasks = install(app, lambda: bus, pump_cron="0 0 1 1 *")  # type: ignore[arg-type, return-value]
    async with app.open_async():
        await tasks.wakeup()
        await tasks.wakeup()  # слилось с ожидающим, исключения наружу нет
        assert len(app.connector.jobs) == 1  # type: ignore[attr-defined]
        await app.run_worker_async(wait=False, queues=["rt_bus"])
        assert len(bus.started) == 1
        await tasks.wakeup()  # прошлое пробуждение уже работало: новое ставится заново
        await app.run_worker_async(wait=False, queues=["rt_bus"])
    assert len(bus.started) == 2


def test_worker_polls_the_queue_every_second_at_most() -> None:
    """NOTIFY при гонке с выборкой теряется; опрос — верхняя граница ожидания задачи."""
    assert WORKER_OPTIONS["fetch_job_polling_interval"] <= 1.0
