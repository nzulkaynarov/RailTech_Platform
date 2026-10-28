"""D2-2: просроченный заказ поставщику — источник вида очереди `supplier_overdue` и уведомление `supplier_order.overdue`.

Заказ просрочен, когда ожидаемая дата прошла, а он отправлен или подтверждён и не получен. Уведомление — один раз на заказ
(создателю и держателям `supply.manage`); новая дата снимает отметку. Очередь — только держателю права снабжения.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from inventory.tests.support import api
from supply.models import SupplierOrder
from supply.services import orders
from supply.tasks import notify_overdue_orders

from core.models import Notification

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


@pytest.fixture(autouse=True)
def locmem_mail(settings):
    channel = {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "erp@demo.example",
    }
    settings.EMAIL_CHANNELS = {name: dict(channel) for name in ("transactional", "marketing", "system")}
    mail.outbox.clear()


def _order(world, *, days_ago, status="confirmed", supplier="vendor"):
    response = api(world["supply"]).post(
        f"{STOCK}orders/",
        {"supplier_id": world[supplier].pk, "lines": [{"product_id": world["rail"].pk, "quantity": 2}]},
        format="json",
    )
    order = SupplierOrder.objects.get(pk=response.json()["id"])
    order.status = status
    order.expected_date = timezone.localdate() - timedelta(days=days_ago)
    order.save()
    return order


def test_overdue_means_past_expected_date_and_not_received(world):
    late = _order(world, days_ago=3)
    sent_late = _order(world, days_ago=1, status="sent")
    on_time = _order(world, days_ago=-2)
    received = _order(world, days_ago=5, status="received")
    draft = _order(world, days_ago=5, status="draft")
    due_today = _order(world, days_ago=0)
    assert orders.is_overdue(late) and orders.is_overdue(sent_late)
    assert not any(orders.is_overdue(o) for o in (on_time, received, draft, due_today))

    response = api(world["supply"]).get(f"{STOCK}overdue/")
    assert response.status_code == 200
    assert [(row["number"], row["days_overdue"], row["status"]) for row in response.json()["results"]] == [
        (late.number, 3, "confirmed"),
        (sent_late.number, 1, "sent"),
    ], "старшая просрочка первой"
    listing = api(world["reader"]).get(f"{STOCK}orders/", {"overdue": "1"}).json()["results"]
    assert {row["number"] for row in listing} == {late.number, sent_late.number}
    assert all(row["overdue"] for row in listing)


def test_the_queue_source_is_for_the_supply_role_only(world):
    _order(world, days_ago=2)
    assert api(world["engineer"]).get(f"{STOCK}overdue/").status_code == 200, "гл. инженер держит supply.manage"
    for who in ("reader", "shipper", "outsider"):
        assert api(world[who]).get(f"{STOCK}overdue/").status_code == 403, who


def test_notification_goes_once_to_the_supply_holders_and_the_creator(world):
    order = _order(world, days_ago=2)
    first = notify_overdue_orders()
    assert first == {"sent": 2}, "создатель (он же снабженец) и гл. инженер — оба держат supply.manage"
    recipients = set(
        Notification.objects.filter(event_code="supplier_order.overdue").values_list("user__email", flat=True)
    )
    assert recipients == {"supply@demo.test", "engineer@demo.test"}
    note = Notification.objects.filter(user=world["supply"], event_code="supplier_order.overdue").get()
    assert note.event_params["number"] == order.number and note.event_params["days"] == 2
    assert note.link == f"/erp/stock/{order.number}" and note.type.code == "WARNING"
    assert Notification.objects.filter(user=world["reader"]).count() == 0, "читателю — нет"

    assert notify_overdue_orders() == {"sent": 0}, "повторный запуск того же дня ничего не шлёт"
    api(world["supply"]).patch(
        f"{STOCK}orders/{order.pk}/",
        {"expected_date": (timezone.localdate() - timedelta(days=1)).isoformat()},
        format="json",
    )
    assert notify_overdue_orders() == {"sent": 2}, "новая дата снимает отметку: о новой просрочке скажем снова"


def test_orders_that_are_not_late_are_silent(world):
    _order(world, days_ago=-3)
    _order(world, days_ago=2, status="received")
    assert notify_overdue_orders() == {"sent": 0}
    assert Notification.objects.count() == 0


def test_the_daily_beat_task_is_seeded_and_reversible():
    from django_celery_beat.models import PeriodicTask

    task = PeriodicTask.objects.get(name="supply.notify_overdue_orders (daily)")
    assert task.task == "supply.notify_overdue_orders" and task.enabled
    assert str(task.crontab.timezone) == "Asia/Tashkent" and (task.crontab.hour, task.crontab.minute) == ("6", "0")
