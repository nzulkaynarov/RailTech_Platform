"""СЦ-9: «Мои задачи» снабженца и отгружающего — `order_shortage` и `ship_project`.

* Непокрытый товар принятого КП проекта (не отгружено, не в резерве, не заказано) — одна строка `order_shortage` на проект;
  строку получает исполнитель товарной зоны расчёта, а если его нет — все держатели `supply.manage`.
* Товар в резерве проекта с исполнением ждёт отгрузки — строка `ship_project` держателю `fulfillment.manage`.
* «Создать заказ · На дефицит заявки» считает ту же формулу и не заказывает повторно уже отгруженное.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from inventory.models import Reservation, ReservationStatus
from inventory.tests.support import api, make_deal
from inventory.tests.test_stock import _adjust, _reserve
from sales.models import CalcTask, CalcTaskAssignee, CalcZone, Deal, Quote
from supply.models import SupplierOrder
from supply.tests.test_orders import _create, _line, locmem_mail  # noqa: F401

from crm.constants import DealStageCode
from crm.models import DealStage

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"
TASKS = f"{STOCK}tasks/"


def _rows(account, kind=None) -> list[dict]:
    response = api(account).get(TASKS)
    assert response.status_code == 200, response.content
    rows = response.json()["results"]
    return [row for row in rows if kind is None or row["kind"] == kind]


def _approved(world, goods, *, signed=True):
    deal, quote, items = make_deal(world, goods, approved=True, signed=signed)
    Quote.objects.filter(pk=quote.pk).update(approved_at=timezone.now() - timedelta(days=2))
    return deal, quote, items


def _task(deal, *assignees):
    task = CalcTask.objects.create(
        deal=deal, eds_letter_id=uuid.uuid4(), letter_number="ВХ-1/26",
        resolution_text="r", due=timezone.localdate(), decided_at=timezone.now(),
    )  # fmt: skip
    for crm_user_id, user in assignees:
        CalcTaskAssignee.objects.create(task=task, crm_user_id=crm_user_id, zone=CalcZone.GOODS, user=user)
    return task


def _ship(world, reservation, quantity):
    response = api(world["supply"]).post(
        f"{STOCK}shipments/",
        {"deal_id": reservation.deal_id, "lines": [{"reservation_id": reservation.pk, "quantity": quantity}]},
        format="json",
    )
    assert response.status_code == 201, response.content


# ── order_shortage ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_uncovered_goods_give_one_row_per_project(world):
    deal, quote, _items = _approved(world, [(world["rail"], 40), (world["bolt"], 5)])

    (row,) = _rows(world["supply"], "order_shortage")

    assert row["id"] == deal.pk and row["number"] == deal.number
    assert row["client_name"] == "ООО Пример Логистик" and row["supplier_name"] == ""
    assert row["note"] == "Перевод стрелочный Р65 1/11: 40; Болт путевой М22: 5"
    assert (
        row["since"][:19] == Quote.objects.get(pk=quote.pk).approved_at.isoformat()[:19]
    ), "since — approval of the quote"


def test_reserved_ordered_and_shipped_goods_are_not_a_shortage(world):
    _adjust(world, world["rail"], 10)
    deal, _quote, (rail, bolt) = _approved(world, [(world["rail"], 10), (world["bolt"], 5)])
    assert _reserve(world, deal, rail, 10).status_code == 201
    assert [row["note"] for row in _rows(world["supply"], "order_shortage")] == [
        "Болт путевой М22: 5"
    ], "резерв покрывает"

    order = _create(world, [_line(world["bolt"], 5)]).json()
    SupplierOrder.objects.get(pk=order["id"]).lines.update(deal=deal, quote_item=bolt)
    assert _rows(world["supply"], "order_shortage") == [], "черновик заказа покрывает — задача «отправить» уже есть"

    SupplierOrder.objects.filter(pk=order["id"]).update(status="cancelled")
    assert len(_rows(world["supply"], "order_shortage")) == 1, "отменённый заказ не покрывает"


def test_shipped_part_is_not_a_shortage(world):
    """Mutation: without the `shipped` term the reserved-then-shipped quantity is reported as missing again."""
    _adjust(world, world["rail"], 10)
    deal, _quote, (rail,) = _approved(world, [(world["rail"], 10)])
    assert _reserve(world, deal, rail, 10).status_code == 201
    reservation = Reservation.objects.get(quote_item=rail)
    _ship(world, reservation, 10)
    assert Reservation.objects.get(pk=reservation.pk).status == ReservationStatus.FULFILLED

    assert _rows(world["supply"], "order_shortage") == []


def test_only_approved_quote_of_a_project_counts(world):
    make_deal(world, [(world["rail"], 3)], approved=False, signed=True)  # КП не одобрено
    deal, _q, _items = make_deal(world, [(world["rail"], 3)], approved=True, signed=False)  # не проект (расчёт)
    assert _rows(world["supply"], "order_shortage") == []
    deal.stage = DealStage.objects.get(code=DealStageCode.CLOSED_LOST)
    deal.save(update_fields=["stage"])
    assert _rows(world["supply"], "order_shortage") == []


def test_row_goes_to_the_goods_assignee_else_to_every_supply_holder(world):
    deal, _quote, _items = _approved(world, [(world["rail"], 4)])
    assert len(_rows(world["supply"], "order_shortage")) == 1
    assert len(_rows(world["engineer"], "order_shortage")) == 1, "исполнителя нет — все держатели права"

    _task(deal, (501, world["supply"]))

    assert len(_rows(world["supply"], "order_shortage")) == 1
    assert _rows(world["engineer"], "order_shortage") == [], "назван другой человек"
    assert _rows(world["shipper"], "order_shortage") == [], "без supply.manage строки снабжения не приходят"


def test_goods_assignee_without_an_erp_account_falls_back_to_all(world):
    deal, _quote, _items = _approved(world, [(world["rail"], 4)])
    _task(deal, (502, None))
    assert len(_rows(world["engineer"], "order_shortage")) == 1


def test_number_of_queries_does_not_grow_with_projects(world):
    _approved(world, [(world["rail"], 4)])
    with CaptureQueriesContext(connection) as one:
        _rows(world["supply"])
    for _ in range(3):
        deal, _q, _i = _approved(world, [(world["rail"], 4), (world["bolt"], 2)])
        _task(deal, (503, world["supply"]))
    with CaptureQueriesContext(connection) as many:
        assert len(_rows(world["supply"], "order_shortage")) == 4
    assert len(many) <= len(one) + 3, (len(one), len(many))


# ── ship_project ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_reserved_goods_with_fulfillment_wait_for_the_shipper(world):
    _adjust(world, world["rail"], 10)
    deal, _quote, (rail,) = _approved(world, [(world["rail"], 10)])
    assert _reserve(world, deal, rail, 10).status_code == 201

    (row,) = _rows(world["shipper"], "ship_project")
    assert row["id"] == deal.pk and row["number"] == deal.number and row["note"] == "в резерве 10"
    assert row["client_name"] == "ООО Пример Логистик"
    assert _rows(world["shipper"], "order_shortage") == []
    assert len(_rows(world["supply"], "ship_project")) == 1, "снабженец тоже отгружает"

    reservation = Reservation.objects.get(quote_item=rail)
    _ship(world, reservation, 4)
    assert _rows(world["shipper"], "ship_project")[0]["note"] == "в резерве 6", "остаток после частичной отгрузки"
    _ship(world, reservation, 6)
    assert _rows(world["shipper"], "ship_project") == [], "отгружено всё — задачи нет"


def test_no_shipment_row_without_a_fulfillment(world):
    _adjust(world, world["rail"], 10)
    deal, _quote, (rail,) = _approved(world, [(world["rail"], 10)])
    assert _reserve(world, deal, rail, 10).status_code == 201
    Deal.objects.get(pk=deal.pk).fulfillment.delete()  # отгрузка без исполнения даст 409 — не предлагаем её
    assert _rows(world["shipper"], "ship_project") == []


def test_list_needs_supply_or_fulfillment_right(world):
    assert api(world["shipper"]).get(TASKS).status_code == 200
    assert api(world["reader"]).get(TASKS).status_code == 403
    assert api(world["outsider"]).get(TASKS).status_code == 403
    assert [row["kind"] for row in _rows(world["shipper"])] == [], "строк снабжения у отгружающего нет"


# ── create_from_deal: не заказывать отгруженное повторно ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shipped", [4, 10])
def test_order_on_shortage_does_not_reorder_shipped_goods(world, shipped):
    """Mutation: without the `shipped` term a fulfilled (or partly shipped) reservation is ordered again."""
    _adjust(world, world["rail"], 10)
    deal, _quote, (rail,) = _approved(world, [(world["rail"], 10)])
    assert _reserve(world, deal, rail, 10).status_code == 201
    _ship(world, Reservation.objects.get(quote_item=rail), shipped)

    response = api(world["supply"]).post(
        f"{STOCK}orders/from-deal/", {"deal_id": deal.pk, "supplier_id": world["vendor"].pk}, format="json"
    )

    assert response.status_code == 409 and response.json() == {"detail": "NO_SHORTAGE"}
    assert not SupplierOrder.objects.exists()


# ── колокольчик о дефиците без партнёра ─────────────────────────────────────────────────────────────────────────────


def test_shortage_notice_links_the_project_and_names_the_purchase_screen(world):
    """Mutation: without `deal=` the bell of the Platform has no link to the project."""
    from supply.services.provision import provision_accepted_quote

    from notifications.models import Notification

    deal, quote, _items = make_deal(world, [(world["bolt"], 5)], approved=True, signed=True)
    Deal.objects.filter(pk=deal.pk).update(manager=world["supply"])
    deal.refresh_from_db()

    provision_accepted_quote(quote)

    note = Notification.objects.get(user=world["supply"], event_code="supply.shortage_without_supplier")
    assert note.deal_id == deal.pk
    assert "Закупки · Новый заказ · На дефицит заявки" in note.message and "Склад · Создать заказ" not in note.message
