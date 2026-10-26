"""Задачи Celery (ERP): регистрация, расписание beat, pump и обработка inbox через очередь (eager)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import pytest
from celery import Celery
from django.db import transaction

from rt_bus import HandlerRegistry
from rt_bus.contrib.celery import install
from rt_bus.django.bus import DjangoBus

from ..conftest import example, example_data, signed
from .conftest import SyncHub
from .test_django_bus import publish

pytestmark = pytest.mark.pg


def test_celery_tasks(make_bus: Callable[..., DjangoBus]) -> None:
    app = Celery("rt-bus-test", broker="memory://")
    app.conf.task_always_eager = True
    app.conf.beat_schedule = {"existing": {"task": "x", "schedule": 60.0}}
    erp = make_bus("erp")
    tasks = install(app, lambda: erp, pump_seconds=3)
    assert {"rt_bus.pump", "rt_bus.process_inbox", "rt_bus.requeue_stuck_inbox", "rt_bus.log_metrics"} <= set(app.tasks)
    schedule = app.conf.beat_schedule
    assert schedule["rt_bus.pump"]["schedule"] == 3
    assert "existing" in schedule

    publish(erp)
    erp.wakeup = tasks.wakeup
    tasks.pump.delay()
    assert [d.status for d in erp.list_deliveries()] == ["delivered"]

    registry = HandlerRegistry()
    handled: list[str] = []
    registry.add("uz.railtech.erp.quote.sent.v1", lambda event: handled.append(event.id))
    crm = make_bus("crm", registry=registry)
    app2 = Celery("rt-bus-test-crm", broker="memory://")
    app2.conf.task_always_eager = True
    crm.enqueue = install(app2, lambda: crm).enqueue
    env = {**example("erp/quote.sent.v1"), "id": str(uuid.uuid4())}
    headers, body = signed(env)
    assert crm.receive(headers, body).body["status"] == "received"
    assert handled == [env["id"]]
    assert [r.status for r in crm.list_inbox()] == ["processed"]


def test_commit_wakes_pump_without_waiting_for_beat(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    """Доставка начинается сразу после коммита транзакции с publish: без ожидания периодического прохода."""
    app = Celery("rt-bus-test-wakeup", broker="memory://")
    app.conf.task_always_eager = True
    erp = make_bus("erp")
    tasks = install(app, lambda: erp)
    erp.wakeup = tasks.wakeup
    started = time.monotonic()
    with transaction.atomic():
        erp.publish("uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
        erp.publish("uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
        assert hub.to("crm") == []  # до коммита ничего не ушло
    elapsed = time.monotonic() - started
    assert [d.status for d in erp.list_deliveries()] == ["delivered", "delivered"]
    assert len(hub.to("crm")) == 2
    assert elapsed < 2


def test_rolled_back_transaction_does_not_wake_pump(make_bus: Callable[..., DjangoBus], hub: SyncHub) -> None:
    app = Celery("rt-bus-test-rollback", broker="memory://")
    app.conf.task_always_eager = True
    erp = make_bus("erp")
    sent: list[int] = []
    tasks = install(app, lambda: erp)

    def wakeup() -> None:
        sent.append(1)
        tasks.wakeup()

    erp.wakeup = wakeup

    def change_then_fail() -> None:
        with transaction.atomic():
            erp.publish("uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
            raise RuntimeError("business failed")

    with pytest.raises(RuntimeError):
        change_then_fail()
    assert sent == []
    assert hub.requests == []


def test_wakeup_targets_the_queue_of_the_beat_task(make_bus: Callable[..., DjangoBus]) -> None:
    """Пробуждение идёт в ту же очередь, что и периодический pump, а не в «ничью»."""

    def queue_of(app: Celery, task: object) -> str:
        options = task._get_exec_options()  # type: ignore[attr-defined]
        return str(app.amqp.router.route(options, "rt_bus.pump")["queue"].name)

    erp = make_bus("erp")
    named = Celery("rt-bus-test-queue", broker="memory://")
    assert queue_of(named, install(named, lambda: erp, queue="bus").pump) == "bus"
    routed = Celery("rt-bus-test-queue2", broker="memory://")
    routed.conf.task_default_queue = "default"
    assert queue_of(routed, install(routed, lambda: erp).pump) == "default"
