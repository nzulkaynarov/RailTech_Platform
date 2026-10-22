"""Задачи Procrastinate (CRM): регистрация, периодические задачи, постановка обработки inbox в очередь."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession

from rt_bus import Event, HandlerRegistry
from rt_bus.contrib.procrastinate import install
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
