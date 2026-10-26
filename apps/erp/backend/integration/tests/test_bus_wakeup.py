"""Пробуждение ретранслятора rt_bus по коммиту в ERP (B5a, `docs/architecture/rt-bus.md` §4 и §7).

Публикация в `transaction.atomic()` ставит задачу `rt_bus.pump` в Celery сразу после коммита (`transaction.on_commit`) —
доставка начинается не позже чем через секунды, а не на ближайшем тике Beat (5 с). Периодический проход остаётся страховкой.
Здесь проверяется ERP-часть: настоящая шина и настоящие задачи Celery (eager — `pump` выполняется в процессе теста),
очередь, которую обслуживает воркер, откат, дедупликация на транзакцию и отказ брокера. Правила библиотеки — в `packages/rt-bus/tests`.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest
from django.db import transaction
from integration.bus import get_bus
from integration.services import events
from integration.tests.world import make_company
from kombu.exceptions import OperationalError
from rt_bus.django.models import Delivery, Outbox

pytestmark = pytest.mark.django_db(transaction=True)

#: Очереди, которые обслуживает `erp-worker` (`infra/compose/base.yml`: `-Q default,pdf,imports`).
SERVED_QUEUES = {"default", "pdf", "imports"}


@pytest.fixture
def eager():
    """Celery выполняет задачи в процессе теста: `pump` реально раскладывает outbox и доставляет."""
    from core.celery import app

    previous = app.conf.task_always_eager
    app.conf.task_always_eager = True
    yield
    app.conf.task_always_eager = previous


@pytest.fixture
def crm_answers(monkeypatch):
    """Подписчик CRM отвечает 200; запросы копятся в списке."""
    requests: list[httpx.Request] = []

    def answer(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "received"})

    monkeypatch.setattr(get_bus(), "_http", httpx.Client(transport=httpx.MockTransport(answer)))
    return requests


def _publish(company, count=1):
    for _ in range(count):
        events.publish_event("invite.sent", company.pk, {"channels": ["email"]})


def test_commit_starts_delivery_without_waiting_for_the_periodic_pump(eager, crm_answers):
    company = make_company(crm_client_id=42)
    started = time.monotonic()
    with transaction.atomic():
        _publish(company)
        assert crm_answers == [], "до коммита ничего не уходит"
    elapsed = time.monotonic() - started
    assert [d.status for d in Delivery.objects.filter(subscriber="crm")] == ["delivered"]
    assert len(crm_answers) == 1
    assert elapsed < 2, f"от коммита до доставки {elapsed:.2f} с"


def test_rollback_does_not_wake_the_pump(eager, crm_answers, monkeypatch):
    from core.celery import bus_tasks

    calls = []
    monkeypatch.setattr(bus_tasks.pump, "apply_async", lambda *a, **kw: calls.append(kw))
    company = make_company(crm_client_id=42)
    with pytest.raises(RuntimeError), transaction.atomic():
        _publish(company)
        raise RuntimeError("business failed")
    assert calls == [] and crm_answers == []
    assert not Outbox.objects.exists()


def test_many_publishes_in_one_transaction_wake_the_pump_once(monkeypatch):
    from core.celery import bus_tasks

    calls = []
    monkeypatch.setattr(bus_tasks.pump, "apply_async", lambda *a, **kw: calls.append(kw))
    company = make_company(crm_client_id=42)
    with transaction.atomic():
        _publish(company, 3)
        with transaction.atomic():
            _publish(company)
    assert len(calls) == 1
    assert Outbox.objects.count() == 4
    with transaction.atomic():
        _publish(company)
    assert len(calls) == 2


def test_broker_failure_neither_breaks_the_commit_nor_loses_the_event(monkeypatch, caplog):
    from core.celery import bus_tasks

    def broker_down(*args, **kwargs):
        raise ConnectionError("redis-broker is down")

    monkeypatch.setattr(bus_tasks.pump, "apply_async", broker_down)
    company = make_company(crm_client_id=42)
    with caplog.at_level(logging.ERROR, logger="rt_bus"):
        with transaction.atomic():
            _publish(company)
    assert "rt_bus_wakeup_failed" in caplog.text
    assert Outbox.objects.count() == 1, "событие в outbox: его подберёт периодический pump"
    assert get_bus().relay() == 1


def test_wakeup_is_wired_into_the_bus_and_goes_to_a_queue_the_worker_serves():
    from core.celery import app, bus_tasks

    assert get_bus().wakeup == bus_tasks.wakeup
    options = bus_tasks.pump._get_exec_options()
    queue = app.amqp.router.route(options, "rt_bus.pump")["queue"].name
    assert queue in SERVED_QUEUES, f"rt_bus.pump уходит в очередь {queue!r}, которую никто не обслуживает"
    beat = app.conf.beat_schedule["rt_bus.pump"]
    assert app.amqp.router.route(beat.get("options", {}), beat["task"])["queue"].name == queue


def test_a_black_hole_broker_does_not_hold_the_commit_for_the_os_timeout():
    """Адрес брокера, куда пакеты не доходят: подключение обрывается по `socket_connect_timeout`, а не через ~75 с."""
    from core.celery import app

    options = app.conf.broker_transport_options
    assert options["socket_connect_timeout"] <= 1
    assert options["socket_timeout"] >= 2, "блокирующее чтение воркера не должно рваться"
    started = time.monotonic()
    with app.connection_for_write(
        "redis://10.255.255.1:6379/1"
    ) as connection:  # те же настройки транспорта, что у `.delay()`
        with pytest.raises(OperationalError):
            connection.ensure_connection(max_retries=1, interval_start=0, interval_step=0.2)
    assert time.monotonic() - started < 8
