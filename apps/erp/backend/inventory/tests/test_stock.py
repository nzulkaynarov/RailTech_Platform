"""D2-2: склад — остатки, резервы, корректировки, отгрузки (`/api/v1/stock/*`, `inventory.services.stock`).

Матрица ролей: снабженец (`supply.manage` + `fulfillment.manage`) действует; «отгрузчик» (`fulfillment.manage`) только
отгружает; роль без прав ERP (`erp.stock: read`) и гл. инженер без `supply.manage`-кода читают/действуют по своим кодам;
не сотрудник — 403 на всё, в том числе чтение.
"""

from __future__ import annotations

import pytest
from inventory.models import Reservation, ReservationStatus, Shipment, StockBalance, StockMovement
from inventory.tests.support import api, make_deal

from crm.constants import FulfillmentStatusCode
from crm.models import ActivityLog, Fulfillment

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _adjust(world, product, quantity, *, cell="A-01", account=None):
    return api(account or world["supply"]).post(
        f"{STOCK}adjustments/", {"product_id": product.pk, "quantity": quantity, "cell": cell}, format="json"
    )


def _reserve(world, deal, item, quantity, account=None):
    return api(account or world["supply"]).post(
        f"{STOCK}reservations/",
        {"deal_id": deal.pk, "quote_item_id": item.pk, "quantity": quantity},
        format="json",
    )


def _row(world, product, account=None):
    rows = api(account or world["supply"]).get(f"{STOCK}balances/", {"q": product.name}).json()["results"]
    return next(row for row in rows if row["product_id"] == product.pk)


# ── остатки и корректировки ─────────────────────────────────────────────────────────────────────────────────────────


def test_adjust_adds_stock_in_a_cell_and_writes_the_journal(world):
    response = _adjust(world, world["rail"], 10, cell="A-03-2")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["on_hand"], body["reserved"], body["free"]) == (10, 0, 10)
    assert body["cells"] == [{"cell": "A-03-2", "on_hand": 10}]
    assert [(m["kind"], m["quantity"], m["cell"]) for m in body["movements"]] == [("adjustment", 10, "A-03-2")]
    assert StockBalance.objects.get(product=world["rail"]).on_hand == 10
    assert StockMovement.objects.count() == 1


def test_adjust_never_goes_below_zero_or_below_reservations(world):
    _adjust(world, world["rail"], 5)
    assert _adjust(world, world["rail"], -6).json() == {"detail": "NOT_ENOUGH_STOCK", "free": 5}
    assert _adjust(world, world["rail"], 0).status_code == 400
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)])
    assert _reserve(world, deal, item, 4).status_code == 201
    refused = _adjust(world, world["rail"], -2)
    assert refused.status_code == 409 and refused.json()["detail"] == "BELOW_RESERVED"
    assert _adjust(world, world["rail"], -1).status_code == 200


def test_services_have_no_stock(world):
    response = _adjust(world, world["mounting"], 1)
    assert response.status_code == 409 and response.json() == {"detail": "SERVICE_NOT_STOCKED"}


def test_balances_show_only_what_matters_and_search_finds_any_product(world):
    _adjust(world, world["rail"], 3)
    rows = api(world["reader"]).get(f"{STOCK}balances/").json()
    assert [row["name"] for row in rows["results"]] == ["Перевод стрелочный Р65 1/11"]
    assert rows["rights"] == {"manage": False, "ship": False}
    found = api(world["supply"]).get(f"{STOCK}balances/", {"q": "болт"}).json()["results"]
    assert [(row["name"], row["on_hand"]) for row in found] == [("Болт путевой М22", 0)], "без остатка, но находится"
    assert api(world["supply"]).get(f"{STOCK}balances/", {"q": "монтаж"}).json()["results"] == [], "услуг на складе нет"


# ── резервы ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_reserve_holds_free_stock_for_a_line_and_can_be_changed_and_released(world):
    _adjust(world, world["rail"], 10, cell="A-01")
    deal, _q, (item,) = make_deal(world, [(world["rail"], 4)])
    first = _reserve(world, deal, item, 3)
    assert first.status_code == 201, first.json()
    assert first.json()["remaining"] == 3 and first.json()["deal"]["id"] == deal.pk
    row = _row(world, world["rail"])
    assert (row["on_hand"], row["reserved"], row["free"]) == (10, 3, 7)

    again = _reserve(world, deal, item, 4)
    assert (
        again.status_code == 201 and again.json()["id"] == first.json()["id"]
    ), "резерв строки один: количество меняется"
    assert Reservation.objects.filter(quote_item=item).count() == 1
    assert _row(world, world["rail"])["free"] == 6

    released = api(world["supply"]).delete(f"{STOCK}reservations/{first.json()['id']}/")
    assert released.status_code == 200 and released.json()["status"] == "released"
    assert _row(world, world["rail"])["free"] == 10
    repeat = api(world["supply"]).delete(f"{STOCK}reservations/{first.json()['id']}/")
    assert repeat.status_code == 409 and repeat.json() == {"detail": "RESERVATION_NOT_ACTIVE"}


def test_reserve_refuses_more_than_free_and_more_than_the_line(world):
    _adjust(world, world["rail"], 5)
    deal_a, _q, (item_a,) = make_deal(world, [(world["rail"], 4)])
    deal_b, _q, (item_b,) = make_deal(world, [(world["rail"], 4)])
    assert _reserve(world, deal_a, item_a, 4).status_code == 201
    other = _reserve(world, deal_b, item_b, 3)
    assert other.status_code == 409 and other.json() == {"detail": "NOT_ENOUGH_STOCK", "free": 1}
    assert _reserve(world, deal_b, item_b, 1).status_code == 201
    too_many = _reserve(world, deal_a, item_a, 5)
    assert too_many.status_code == 400 and too_many.json()["detail"] == "QUANTITY_OUT_OF_RANGE"


def test_reserve_object_checks(world):
    _adjust(world, world["rail"], 5)
    deal, _q, (item,) = make_deal(world, [(world["rail"], 2)])
    other_deal, _q2, _items = make_deal(world, [(world["bolt"], 2)])
    # строка чужой заявки не резервируется через эту
    assert _reserve(world, other_deal, item, 1).status_code == 404
    # заявка закрыта — резерв не берётся
    deal.stage = type(deal.stage).objects.get(code="CLOSED_LOST")
    deal.save()
    closed = _reserve(world, deal, item, 1)
    assert closed.status_code == 409 and closed.json() == {"detail": "DEAL_CLOSED"}


def test_a_lost_deal_does_not_hold_stock(world):
    _adjust(world, world["rail"], 5)
    deal, _q, (item,) = make_deal(world, [(world["rail"], 5)])
    assert _reserve(world, deal, item, 5).status_code == 201
    assert _row(world, world["rail"])["free"] == 0
    deal.stage = type(deal.stage).objects.get(code="CLOSED_LOST")
    deal.save()
    assert _row(world, world["rail"])["free"] == 5, "проигранная заявка резерв не держит"


def test_a_line_without_a_catalog_card_cannot_be_reserved(world):
    from crm.models import CalcLine, QuoteItem

    deal, quote, _items = make_deal(world, [(world["rail"], 1)])
    free_text = QuoteItem(quote=quote, position=9, imported_raw_name="Нечто без карточки", quantity=1)
    free_text.save(skip_recalculate=True)
    CalcLine.objects.create(item=free_text)
    refused = _reserve(world, deal, free_text, 1)
    assert refused.status_code == 409 and refused.json() == {"detail": "PRODUCT_REQUIRED"}


def test_reservations_follow_the_line_when_it_changes(world):
    _adjust(world, world["rail"], 10)
    deal, quote, (item,) = make_deal(world, [(world["rail"], 5)])
    reservation_id = _reserve(world, deal, item, 5).json()["id"]
    item.quantity = 2
    item.save(skip_recalculate=True)
    from inventory.services import stock

    stock.sync_reservation(item)
    assert Reservation.objects.get(pk=reservation_id).quantity == 2
    item.product = world["bolt"]
    item.save(skip_recalculate=True)
    stock.sync_reservation(item)
    assert Reservation.objects.get(pk=reservation_id).status == ReservationStatus.RELEASED


# ── права ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_role_matrix_on_stock_mutations(world):
    deal, _q, (item,) = make_deal(world, [(world["rail"], 2)])
    _adjust(world, world["rail"], 5)
    for who in ("reader", "shipper", "outsider"):
        assert _adjust(world, world["rail"], 1, account=world[who]).status_code == 403, who
        assert _reserve(world, deal, item, 1, account=world[who]).status_code == 403, who
    assert (
        _adjust(world, world["rail"], 1, account=world["engineer"]).status_code == 200
    ), "у гл. инженера есть supply.manage"


def test_everything_is_closed_to_a_non_employee_even_for_reading(world):
    outsider = api(world["outsider"])
    for path in (
        "balances/",
        "balances/1/",
        "reservations/",
        "shipments/",
        "suppliers/",
        "orders/",
        "receipts/",
        "price-requests/",
    ):
        assert outsider.get(f"{STOCK}{path}").status_code == 403, path
    assert api(world["reader"]).get(f"{STOCK}overdue/").status_code == 403, "очередь — для держателя снабжения"


# ── отгрузки ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_shipping_reduces_stock_and_reservation_and_numbers_the_waybill(world):
    _adjust(world, world["rail"], 10, cell="A-01")
    deal, _q, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    reservation = _reserve(world, deal, item, 4).json()
    shipped = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {
            "deal_id": deal.pk,
            "lines": [{"reservation_id": reservation["id"], "quantity": 3}],
            "tracking": "TRK-001",
            "carrier": "ООО Перевозка",
        },
        format="json",
    )
    assert shipped.status_code == 201, shipped.json()
    body = shipped.json()
    year = Shipment.objects.get().number_year
    assert body["number"] == f"ОТГ-{year}-001" and body["tracking"] == "TRK-001"
    assert [(line["quantity"], line["cell"]) for line in body["lines"]] == [(3, "A-01")]
    row = _row(world, world["rail"])
    assert (row["on_hand"], row["reserved"], row["free"]) == (7, 1, 6)
    assert Reservation.objects.get(pk=reservation["id"]).shipped_quantity == 3
    assert Fulfillment.objects.get(deal=deal).status.code == FulfillmentStatusCode.PENDING, "товар ушёл не весь"

    last = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 1}], "tracking": "TRK-002"},
        format="json",
    )
    assert last.status_code == 201 and last.json()["number"] == f"ОТГ-{year}-002"
    assert Reservation.objects.get(pk=reservation["id"]).status == ReservationStatus.FULFILLED
    fulfillment = Fulfillment.objects.get(deal=deal)
    assert (
        fulfillment.status.code == FulfillmentStatusCode.SHIPPED and fulfillment.tracking_number == "TRK-002"
    ), "весь товар отгружен — исполнение сделки «Отгружено» существующим путём"
    assert _row(world, world["rail"])["on_hand"] == 6
    assert ActivityLog.objects.filter(deal=deal, event_code="stock.shipped").count() == 2


def test_shipment_guards(world):
    _adjust(world, world["rail"], 10)
    deal, _q, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    reservation = _reserve(world, deal, item, 4).json()

    def ship(body, account="shipper"):
        return api(world[account]).post(f"{STOCK}shipments/", body, format="json")

    over = ship({"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 5}]})
    assert over.status_code == 400 and over.json()["detail"] == "QUANTITY_OUT_OF_RANGE"
    other_deal, _q2, (other_item,) = make_deal(world, [(world["bolt"], 1)], approved=True, signed=True)
    foreign = ship({"deal_id": other_deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 1}]})
    assert foreign.status_code == 404, "резерв чужой заявки не отгружается через эту"
    assert ship({"deal_id": deal.pk, "lines": []}).status_code == 400
    duplicate = ship({"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 1}] * 2})
    assert duplicate.status_code == 400
    assert (
        ship(
            {"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 1}]}, "reader"
        ).status_code
        == 403
    )
    assert (
        ship(
            {"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 1}]}, "outsider"
        ).status_code
        == 403
    )
    assert Shipment.objects.count() == 0 and _row(world, world["rail"])["on_hand"] == 10, "отказы ничего не списали"


def test_shipping_before_the_contract_is_refused(world):
    _adjust(world, world["rail"], 5)
    deal, _q, (item,) = make_deal(world, [(world["rail"], 2)])
    reservation = _reserve(world, deal, item, 2).json()
    refused = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 2}]},
        format="json",
    )
    assert refused.status_code == 409 and refused.json() == {"detail": "FULFILLMENT_NOT_READY"}


def test_shipments_listing(world):
    _adjust(world, world["rail"], 5)
    deal, _q, (item,) = make_deal(world, [(world["rail"], 2)], approved=True, signed=True)
    reservation = _reserve(world, deal, item, 2).json()
    api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation["id"], "quantity": 2}]},
        format="json",
    )
    listing = api(world["reader"]).get(f"{STOCK}shipments/", {"deal_id": deal.pk}).json()
    assert [s["deal"]["id"] for s in listing["results"]] == [deal.pk]
    assert listing["rights"] == {"manage": False, "ship": False}
