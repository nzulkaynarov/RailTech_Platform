"""D2-2 / B-D21-1: колонка «Склад» расчёта берёт остаток, ячейку и резерв из склада.

Учёт движений по товару ведётся — «На складе» и «Свободно» оттуда (с вычетом резервов других проектов), ячейка — с
наибольшим остатком, «Зарезервировано» — за этой строкой; нет учёта — прежнее поведение D2-1 (своё предложение). Резерв
строки не сбрасывает визу, удаление строки снимает резерв.
"""

from __future__ import annotations

import pytest
from inventory.models import Reservation, ReservationStatus

from crm.models import CalcLine, Deal, QuoteItem
from crm.tests.test_calc import SUPPLY, _api, _sheet, _staff, _started, _url, world  # noqa: F401

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


@pytest.fixture(autouse=True)
def stocker(world):  # noqa: F811
    """Снабженец со складом: роль каталога SUPPLY + `erp.stock` полный (`supply.manage`, `fulfillment.manage`)."""
    world["stocker"] = _staff(world["seller"], "stocker@demo.test", [*SUPPLY, "supply.manage", "fulfillment.manage"])


def _adjust(account, product, quantity, cell="A-01"):
    return _api(account).post(
        f"{STOCK}adjustments/", {"product_id": product.pk, "quantity": quantity, "cell": cell}, format="json"
    )


def _reserve(world, item_id, quantity):  # noqa: F811
    return _api(world["stocker"]).post(
        f"{STOCK}reservations/",
        {"deal_id": world["deal"].pk, "quote_item_id": item_id, "quantity": quantity},
        format="json",
    )


def test_without_movements_the_stock_column_keeps_the_offer_behaviour(world):  # noqa: F811
    _started(world)
    goods = _sheet(world, world["supply"])["lines"][0]
    assert goods["stock"] == {"on_hand": 1, "free": 1, "cell": None, "reserved": 0}
    assert goods["kind"] == "goods_to_order", "на складе 1, нужно 2"


def test_stock_column_shows_cell_free_and_reserved_and_follows_reservations(world):  # noqa: F811
    goods_id, _service_id = _started(world)
    assert _adjust(world["stocker"], world["rail"], 5, "B-04-1").status_code == 200

    line = _sheet(world, world["supply"])["lines"][0]
    assert line["stock"] == {"on_hand": 5, "free": 5, "cell": "B-04-1", "reserved": 0}
    assert line["kind"] == "goods", "свободного остатка хватает — товар со склада"

    assert _reserve(world, goods_id, 2).status_code == 201
    line = _sheet(world, world["supply"])["lines"][0]
    assert line["stock"] == {"on_hand": 5, "free": 3, "cell": "B-04-1", "reserved": 2}
    assert line["kind"] == "goods" and line["group"] == "stock"

    # резерв другого проекта съедает свободное: строке остаётся только её резерв
    other = Deal.objects.create(title="Другая", company=world["deal"].company, stage=world["deal"].stage)
    from crm.models import Quote

    quote = Quote.objects.create(
        deal=other,
        version=1,
        prepared_by=world["supply"],
        status=Quote.objects.first().status,
        seller_company=world["seller"],
    )
    taken = QuoteItem(quote=quote, position=1, product=world["rail"], imported_raw_name="x", quantity=3)
    taken.save(skip_recalculate=True)
    CalcLine.objects.create(item=taken)
    reserved_elsewhere = _api(world["stocker"]).post(
        f"{STOCK}reservations/", {"deal_id": other.pk, "quote_item_id": taken.pk, "quantity": 3}, format="json"
    )
    assert reserved_elsewhere.status_code == 201
    line = _sheet(world, world["supply"])["lines"][0]
    assert line["stock"] == {"on_hand": 5, "free": 0, "cell": "B-04-1", "reserved": 2}
    assert line["kind"] == "goods", "свой резерв (2) покрывает количество строки (2)"


def test_reserve_keeps_the_visa_and_delete_releases_the_reservation(world):  # noqa: F811
    goods_id, _service_id = _started(world)
    _adjust(world["stocker"], world["rail"], 5)
    patched = _api(world["supply"]).patch(
        _url(world, f"lines/{goods_id}/"), {"purchase_price": "1000.00", "client_price": "1500.00"}, format="json"
    )
    assert patched.status_code == 200, patched.json()
    assert _api(world["supply"]).post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    assert _reserve(world, goods_id, 2).status_code == 201
    assert _sheet(world, world["supply"])["lines"][0]["visa"] is not None, "резерв — не правка строки"

    deleted = _api(world["supply"]).delete(_url(world, f"lines/{goods_id}/"))
    assert deleted.status_code == 200
    assert Reservation.objects.get().status == ReservationStatus.RELEASED


def test_changing_the_quantity_trims_the_reservation(world):  # noqa: F811
    goods_id, _service_id = _started(world)
    _adjust(world["stocker"], world["rail"], 5)
    _reserve(world, goods_id, 2)
    assert (
        _api(world["supply"]).patch(_url(world, f"lines/{goods_id}/"), {"quantity": 1}, format="json").status_code
        == 200
    )
    assert Reservation.objects.get().quantity == 1


def test_rights_expose_the_stock_flag_and_the_catalog_uses_free_stock(world):  # noqa: F811
    _started(world)
    assert _sheet(world, world["stocker"])["rights"]["stock"] is True
    assert _sheet(world, world["supply"])["rights"]["stock"] is False, "виза товаров без права снабжения склад не ведёт"
    assert _sheet(world, world["engineer"])["rights"]["stock"] is False
    assert _sheet(world, world["accountant"])["rights"]["stock"] is False
    _adjust(world["stocker"], world["rail"], 4)
    found = _api(world["supply"]).get("/api/v1/calc/catalog/", {"q": "стрелочный"}).json()["results"]
    assert [row["on_hand"] for row in found] == [4]
