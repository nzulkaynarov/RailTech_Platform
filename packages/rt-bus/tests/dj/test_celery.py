"""Задачи Celery (ERP): регистрация, расписание beat, pump и обработка inbox через очередь (eager)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from celery import Celery

from rt_bus import HandlerRegistry
from rt_bus.contrib.celery import install
from rt_bus.django.bus import DjangoBus

from ..conftest import example, signed
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
