"""Журнал и эксплуатация шины в ERP (B3): задачи Celery и Beat, «повторить», `manage.py bus_retry`, метрики.

Замена журнала вебхуков ERP → CRM: повтор доставки, «повторить все dead» по подписчику и повтор обработки
входящего — из админки (только суперпользователю, с причиной и записью в журнал доступа) и из командной строки.
"""

from __future__ import annotations

import io

import httpx
import pytest
from django.contrib.admin.sites import site
from django.core.management import CommandError, call_command
from django.db import transaction
from integration.bus import get_bus
from integration.services import events
from integration.tests.world import make_company
from rt_bus.django.models import Delivery, Inbox

from accounts.models import CustomUser


def _dead_delivery(monkeypatch):
    """Событие, доставка которого ушла в `dead` (подписчик ответил 404 — неверный адрес)."""
    company = make_company(crm_client_id=42)
    with transaction.atomic():
        event = events.publish_event("invite.sent", company.pk, {"channels": ["email"]})
    bus = get_bus()
    monkeypatch.setattr(bus, "_http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    bus.pump()
    delivery = Delivery.objects.get(event_id=event.id)
    assert delivery.status == "dead"
    return delivery


def test_celery_has_the_bus_tasks_and_their_schedule():
    from core.celery import app

    names = {"rt_bus.pump", "rt_bus.process_inbox", "rt_bus.requeue_stuck_inbox", "rt_bus.log_metrics", "rt_bus.purge"}
    app.loader.import_default_modules()
    assert names <= set(app.tasks), sorted(names - set(app.tasks))
    schedule = app.conf.beat_schedule
    assert {"rt_bus.pump", "rt_bus.requeue_stuck_inbox", "rt_bus.log_metrics", "rt_bus.purge"} <= set(schedule)
    assert schedule["rt_bus.pump"]["schedule"] == 5.0
    assert not any("webhook" in key for key in schedule), "задач доставки вебхуков и их расписания больше нет"
    assert "integration.deliver_webhook" + "_event" not in app.tasks


def test_the_bus_serves_the_erp_publisher_and_waits_for_the_celery_queue():
    from core.celery import bus_tasks

    bus = get_bus()
    assert bus.config.service == "erp" and bus.stash is not None
    assert bus.enqueue == bus_tasks.enqueue and bus.wakeup == bus_tasks.wakeup


@pytest.mark.django_db(transaction=True)
def test_bus_retry_command_resends_all_dead_of_a_subscriber(monkeypatch):
    delivery = _dead_delivery(monkeypatch)
    out = io.StringIO()
    call_command("bus_retry", "--list", "--status", "dead", stdout=out)
    assert str(delivery.id) in out.getvalue() and "crm" in out.getvalue()

    call_command("bus_retry", "--all-dead", "--subscriber", "crm", stdout=out)
    assert "Поставлено на повтор (dead): 1" in out.getvalue()
    assert Delivery.objects.get(pk=delivery.pk).status == "pending"

    monkeypatch.setattr(get_bus(), "_http", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    get_bus().pump()
    assert Delivery.objects.get(pk=delivery.pk).status == "delivered"


@pytest.mark.django_db(transaction=True)
def test_bus_retry_command_retries_one_delivery_and_reports_a_missing_one(monkeypatch):
    delivery = _dead_delivery(monkeypatch)
    call_command("bus_retry", "--delivery", str(delivery.id), stdout=io.StringIO())
    assert Delivery.objects.get(pk=delivery.pk).status == "pending"
    with pytest.raises(CommandError):
        call_command("bus_retry", "--delivery", "999999", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command("bus_retry", "--inbox", "00000000-0000-0000-0000-000000000000", stdout=io.StringIO())


@pytest.mark.django_db
def test_bus_retry_metrics_command_prints_the_counters():
    out = io.StringIO()
    call_command("bus_retry", "--metrics", stdout=out)
    assert "dlq_size" in out.getvalue()


@pytest.mark.django_db
def test_bus_journal_models_are_in_the_engineering_admin():
    registered = {model.__name__ for model in site._registry}
    assert {"Delivery", "Inbox", "Outbox", "SubscriberState"} <= registered
    assert "IntegrationWebhook" + "Event" not in registered


@pytest.mark.django_db(transaction=True)
def test_admin_action_retries_dead_deliveries_for_a_superuser_only(monkeypatch, rf):
    delivery = _dead_delivery(monkeypatch)
    model_admin = site._registry[Delivery]
    assert not model_admin.has_change_permission(rf.get("/")) and not model_admin.has_delete_permission(rf.get("/"))
    assert "retry_selected" in model_admin.actions and "retry_all_dead_of_subscribers" in model_admin.actions

    from django.contrib.messages.storage.fallback import FallbackStorage

    def post(user, **extra):
        request = rf.post("/admin/rt_bus/delivery/", {"_selected_action": [delivery.pk], **extra})
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    root = CustomUser.objects.create_user(
        email="root@bus.test", username="root_bus", password="x", is_staff=True, is_superuser=True
    )
    qs = Delivery.objects.filter(pk=delivery.pk)
    from core.admin_mixins import EMERGENCY_CONFIRM_FIELD, EMERGENCY_REASON_FIELD

    request = post(root, **{EMERGENCY_CONFIRM_FIELD: "1", EMERGENCY_REASON_FIELD: "адрес исправлен"})
    model_admin.retry_all_dead_of_subscribers(request, qs)
    assert Delivery.objects.get(pk=delivery.pk).status == "pending"
    messages = [str(m) for m in request._messages]
    assert any("Поставлено на повторную доставку (dead): 1" in m for m in messages)

    # Не суперпользователь: действие отказывает и ничего не меняет.
    Delivery.objects.filter(pk=delivery.pk).update(status="dead")
    staff = CustomUser.objects.create_user(email="eng@bus.test", username="eng_bus", password="x", is_staff=True)
    request = post(staff, **{EMERGENCY_CONFIRM_FIELD: "1", EMERGENCY_REASON_FIELD: "попытка"})
    model_admin.retry_all_dead_of_subscribers(request, qs)
    assert Delivery.objects.get(pk=delivery.pk).status == "dead"


@pytest.mark.django_db
def test_inbox_failed_records_can_be_retried(monkeypatch):
    """Запись inbox в `failed` повторяется из админки/команды; здесь — на уровне шины (обработчик теперь исправен)."""
    from django.utils import timezone
    from integration.tests.test_bus_wiring import crm_event, signed_post

    envelope = crm_event("client.updated")
    signed_post(envelope)
    Inbox.objects.filter(event_id=envelope["id"]).update(status="failed", attempts=4, error="boom")
    monkeypatch.setattr(get_bus(), "enqueue", get_bus().process_inbox)
    assert get_bus().retry_inbox(envelope["id"]) is True
    assert Inbox.objects.get(event_id=envelope["id"]).status in ("received", "processed")
    assert timezone.now()
