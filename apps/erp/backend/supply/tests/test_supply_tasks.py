"""Plan 0.7 (FR-6): the supply officer's to-do list `GET /api/v1/stock/tasks/`.

A draft order, a partner's date change, a shipment not received and a partnership application each give a row; a sent
order, a received shipment and a decided application do not. Only a holder of `supply.manage` sees the list.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from inventory.tests.support import api
from parties.models import PartnerApplication, PartnerApplicationSource, PartnerApplicationStatus, PartnerKind
from supply.models import SupplierOrder, SupplierOrderShipmentNotice

from supply.tests.test_orders import _act, _create, _line, _tomorrow, locmem_mail  # noqa: F401

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/stock/tasks/"


def _application(status=PartnerApplicationStatus.SUBMITTED, **extra) -> PartnerApplication:
    data = {
        "source": PartnerApplicationSource.PUBLIC,
        "company_name": "ООО Завод Металл",
        "inn": "7701234567",
        "contact_name": "Иван Металлов",
        "email": "metal@example.com",
        "phone": "+998901234567",
        "language": "ru",
        "kind": PartnerKind.MANUFACTURER,
        "categories_description": "Рельсы",
        "status": status,
    }
    return PartnerApplication.objects.create(**{**data, **extra})


def _kinds(world) -> list[tuple[str, object]]:
    response = api(world["supply"]).get(TASKS)
    assert response.status_code == 200, response.content
    return [(row["kind"], row["number"] or row["supplier_name"]) for row in response.json()["results"]]


def test_draft_order_and_application_are_tasks_until_acted_on(world):
    draft = _create(world).json()
    _application()
    _application(status=PartnerApplicationStatus.REJECTED, company_name="ООО Отказ")
    kinds = _kinds(world)
    assert ("send_order", draft["number"]) in kinds
    assert ("partner_application", "ООО Завод Металл") in kinds
    assert all(name != "ООО Отказ" for _, name in kinds), "decided application is not a task"

    assert _act(world, draft["id"], "send").status_code == 200
    assert ("send_order", draft["number"]) not in _kinds(world), "a sent order leaves the list"


def test_partner_date_change_and_shipment_wait_for_the_officer(world):
    order_id = _create(world, [_line(world["rail"], 2)]).json()["id"]
    assert _act(world, order_id, "send").status_code == 200
    assert _act(world, order_id, "confirm", {"expected_date": _tomorrow()}).status_code == 200
    order = SupplierOrder.objects.get(pk=order_id)
    wanted = timezone.localdate() + timedelta(days=10)
    SupplierOrder.objects.filter(pk=order_id).update(
        partner_requested_date=wanted, partner_requested_at=timezone.now(), partner_requested_reason="нет вагонов"
    )
    SupplierOrderShipmentNotice.objects.create(order=order, supplier_doc="ТТН-5")

    rows = {row["kind"]: row for row in api(world["supply"]).get(TASKS).json()["results"]}
    assert rows["partner_date_change"]["date"] == wanted.isoformat()
    assert rows["partner_date_change"]["note"] == "нет вагонов"
    assert rows["receive_goods"]["note"] == "ТТН-5" and rows["receive_goods"]["number"] == order.number

    line = api(world["supply"]).get(f"/api/v1/stock/orders/{order_id}/").json()["lines"][0]["id"]
    _act(world, order_id, "receipts", {"lines": [{"order_line_id": line, "quantity": 1}]})
    assert "receive_goods" not in dict(_kinds(world)), "a receipt after the shipment closes the task"

    SupplierOrder.objects.filter(pk=order_id).update(partner_requested_date=None)
    assert "partner_date_change" not in dict(_kinds(world))


def test_only_supply_sees_the_list(world):
    for who in ("reader", "shipper", "outsider"):
        assert api(world[who]).get(TASKS).status_code == 403, who
