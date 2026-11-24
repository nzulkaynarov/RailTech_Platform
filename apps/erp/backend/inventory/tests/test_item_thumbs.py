"""ЕД-4: позиция со ссылкой на фото в каждой строке склада — приёмка, резервы, отгрузки, поиск по номеру.

Строка отдаёт `item` той же формы, что остатки и заказы: `{id, name, sku, kind, photo}`; `photo` — id главного фото, по
нему клиент берёт миниатюру через свой API. Без фото — `photo: null` (значок типа). Адреса хранилища в строках нет.
"""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from inventory.tests.support import api, complete_order, make_deal
from PIL import Image
from supply.models import SupplierOrderLine

from catalog.desk import images
from catalog.models import Category

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _photo(product) -> int:
    out = BytesIO()
    Image.new("RGB", (240, 160), (30, 120, 200)).save(out, format="PNG")
    return images.add_image(product, SimpleUploadedFile("p.png", out.getvalue(), content_type="image/png")).pk


def _expected(product, photo) -> dict:
    return {"id": product.pk, "name": product.name, "sku": product.sku, "kind": "goods", "photo": photo}


@pytest.fixture
def stocked(world):
    """Проект с договором: заказ на два товара — приёмка ждёт; серийный `rail` с фото, `bolt` без фото."""
    world["rail"].category = Category.objects.create(name="Двигатели", tracking="serial")
    world["rail"].save(update_fields=["category"])
    photo = _photo(world["rail"])
    deal, _quote, (rail_item, bolt_item) = make_deal(
        world, [(world["rail"], 2), (world["bolt"], 3)], approved=True, signed=True
    )
    body = {
        "supplier_id": world["vendor"].pk,
        "lines": [
            {"product_id": world["rail"].pk, "quantity": 2, "deal_id": deal.pk, "quote_item_id": rail_item.pk},
            {"product_id": world["bolt"].pk, "quantity": 3, "deal_id": deal.pk, "quote_item_id": bolt_item.pk},
        ],
    }
    order_id = api(world["supply"]).post(f"{STOCK}orders/", body, format="json").json()["id"]
    complete_order(order_id)
    api(world["supply"]).post(f"{STOCK}orders/{order_id}/send/", {}, format="json")
    confirm = {"expected_date": (timezone.localdate() + timedelta(days=1)).isoformat()}
    api(world["supply"]).post(f"{STOCK}orders/{order_id}/confirm/", confirm, format="json")
    ids = {line.product_id: line.pk for line in SupplierOrderLine.objects.filter(order_id=order_id)}
    return {"deal": deal, "order_id": order_id, "ids": ids, "photo": photo}


def _receive(world, stocked):
    lines = [
        {"order_line_id": stocked["ids"][world["rail"].pk], "quantity": 2, "serials": ["SN-1", "SN-2"]},
        {"order_line_id": stocked["ids"][world["bolt"].pk], "quantity": 3},
    ]
    response = api(world["supply"]).post(
        f"{STOCK}orders/{stocked['order_id']}/receipts/", {"lines": lines}, format="json"
    )
    assert response.status_code == 200, response.json()


def test_pending_receipt_line_carries_the_item_with_its_photo(world, stocked):
    pending = {r["name"]: r for r in api(world["supply"]).get(f"{STOCK}receipts/").json()["pending"]}
    assert pending[world["rail"].name]["item"] == _expected(world["rail"], stocked["photo"])
    assert pending[world["bolt"].name]["item"] == _expected(world["bolt"], None), "нет фото — значок типа"


def test_done_receipt_lines_reservations_shipments_and_trace_carry_the_item(world, stocked):
    _receive(world, stocked)
    rail, photo = world["rail"], stocked["photo"]

    done = api(world["supply"]).get(f"{STOCK}receipts/").json()["done"][0]["lines"]
    assert {line["name"]: line["item"] for line in done}[rail.name] == _expected(rail, photo)

    reservations = api(world["supply"]).get(f"{STOCK}reservations/", {"deal_id": stocked["deal"].pk}).json()["results"]
    assert {r["product_id"]: r["item"] for r in reservations}[rail.pk] == _expected(rail, photo)

    traced = api(world["reader"]).get(f"{STOCK}trace/", {"q": "SN-1"}).json()["results"]
    assert traced[0]["product"]["item"] == _expected(rail, photo)

    shipped = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {
            "deal_id": stocked["deal"].pk,
            "lines": [
                {"reservation_id": {r["product_id"]: r["id"] for r in reservations}[world["bolt"].pk], "quantity": 3},
            ],
        },
        format="json",
    )
    assert shipped.status_code == 201, shipped.json()
    listed = api(world["shipper"]).get(f"{STOCK}shipments/").json()["results"]
    assert listed[0]["lines"][0]["item"] == _expected(world["bolt"], None)


def test_no_storage_address_in_stock_rows(world, stocked):
    _receive(world, stocked)
    bodies = [
        api(world["supply"]).get(f"{STOCK}receipts/").content,
        api(world["supply"]).get(f"{STOCK}reservations/").content,
        api(world["reader"]).get(f"{STOCK}trace/", {"q": "SN-1"}).content,
    ]
    for body in bodies:
        assert b"/media/" not in body and b"http" not in body.lower().replace(b"https://example", b"")
