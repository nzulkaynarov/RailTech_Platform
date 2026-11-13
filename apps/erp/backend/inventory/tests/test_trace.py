"""L0-3, ADR-0021: прослеживаемость-минимум — класс S/L/N категории, серийные и партии на приёмке и отгрузке, поиск.

Класс — данные категории (товар наследует): S — серийные номера (число = количеству, без повторов, уникальны в товаре),
L — партия и срок годности, N — как было. Документ соответствия — если категория требует (номер и действующий срок).
Отгрузка S/L — только свободными единицами этого товара, их сумма = количеству строки. Поиск по номеру — откуда (приёмка,
заказ, поставщик, изготовитель, документ) и куда (отгрузка, клиент, проект). Строка заказа поставщику — со ссылкой на цену.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from inventory.models import StockBalance, TraceStatus, TraceUnit
from inventory.tests.support import api, make_deal
from supply.models import GoodsReceiptLine, SupplierOrderLine

from catalog.models import Category, Manufacturer, SupplierOffer
from master_data.models import Currency, DeliveryBasis

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


@pytest.fixture
def classes(world):
    """Категории с классом (данные, а не код): серийная с документом, партия, только количество."""
    serial = Category.objects.create(name="Двигатели", tracking="serial", requires_conformity_doc=True)
    lot = Category.objects.create(name="Смазки", tracking="lot")
    plain = Category.objects.create(name="Мелочь")
    world["rail"].category = serial
    world["rail"].brand = Manufacturer.objects.create(name="Завод Вымышленный")
    world["rail"].save(update_fields=["category", "brand"])
    world["bolt"].category = lot
    world["bolt"].save(update_fields=["category"])
    return {"serial": serial, "lot": lot, "plain": plain}


def _future(days=365):
    return (timezone.localdate() + timedelta(days=days)).isoformat()


def _order(world, lines, who="supply"):
    body = {"supplier_id": world["vendor"].pk, "lines": lines}
    created = api(world[who]).post(f"{STOCK}orders/", body, format="json")
    assert created.status_code == 201, created.json()
    order_id = created.json()["id"]
    assert api(world[who]).post(f"{STOCK}orders/{order_id}/send/", {}, format="json").status_code == 200
    confirm = {"expected_date": _future(1)}
    assert api(world[who]).post(f"{STOCK}orders/{order_id}/confirm/", confirm, format="json").status_code == 200
    return order_id, {line.product_id: line.pk for line in SupplierOrderLine.objects.filter(order_id=order_id)}


def _receive(world, order_id, lines, who="supply"):
    return api(world[who]).post(f"{STOCK}orders/{order_id}/receipts/", {"lines": lines}, format="json")


def _serial_line(line_id, serials, quantity=None, **extra):
    doc = {"doc_number": "СЕРТ-0001", "doc_valid_until": _future()}
    return {"order_line_id": line_id, "quantity": quantity or len(serials), "serials": serials, **doc, **extra}


def _project(world, rail=2, bolt=5):
    """Проект с договором (отгрузка возможна), заказ под него и приёмка: S — 2 серийных, L — партия."""
    deal, _quote, (rail_item, bolt_item) = make_deal(
        world, [(world["rail"], rail), (world["bolt"], bolt)], approved=True, signed=True
    )
    order_id, ids = _order(
        world,
        [
            {"product_id": world["rail"].pk, "quantity": rail, "deal_id": deal.pk, "quote_item_id": rail_item.pk},
            {"product_id": world["bolt"].pk, "quantity": bolt, "deal_id": deal.pk, "quote_item_id": bolt_item.pk},
        ],
    )
    received = _receive(
        world,
        order_id,
        [
            _serial_line(ids[world["rail"].pk], [f"ENG-{n:04d}" for n in range(1, rail + 1)]),
            {"order_line_id": ids[world["bolt"].pk], "quantity": bolt, "lot": "LOT-77", "expiry_date": _future(200)},
        ],
    )
    assert received.status_code == 200, received.json()
    return deal


def _reservations(world, deal):
    rows = api(world["supply"]).get(f"{STOCK}reservations/", {"deal_id": deal.pk}).json()["results"]
    return {row["product_id"]: row for row in rows}


def _ship(world, deal, lines):
    return api(world["shipper"]).post(f"{STOCK}shipments/", {"deal_id": deal.pk, "lines": lines}, format="json")


# ── категория: класс — данные ───────────────────────────────────────────────────────────────────────────────────────


def test_category_tracking_is_data_the_catalog_manager_sets(world):
    category = Category.objects.create(name="Оборудование")
    url = f"/api/v1/catalog/categories/{category.pk}/"
    response = api(world["supply"]).patch(url, {"tracking": "serial", "requires_conformity_doc": True}, format="json")
    assert response.status_code == 200, response.json()
    assert (response.json()["tracking"], response.json()["requires_conformity_doc"]) == ("serial", True)
    assert api(world["supply"]).patch(url, {"tracking": "unit"}, format="json").status_code == 400
    assert api(world["reader"]).patch(url, {"tracking": "lot"}, format="json").status_code == 403
    assert Category.objects.create(name="Новая").tracking == "none", "по умолчанию — только количество"


# ── приёмка ────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("line", "status", "code"),
    [
        ({"serials": []}, 400, "SERIALS_REQUIRED"),
        ({"serials": ["A-1"], "quantity": 2}, 400, "SERIALS_COUNT_MISMATCH"),
        ({"serials": ["A-1", " A-1 "]}, 400, "SERIAL_DUPLICATE"),
        ({"serials": ["A-1", "A-2"], "doc_number": ""}, 400, "CONFORMITY_DOC_REQUIRED"),
        ({"serials": ["A-1", "A-2"], "doc_valid_until": None}, 400, "CONFORMITY_DOC_VALID_UNTIL_REQUIRED"),
        ({"serials": ["A-1", "A-2"], "doc_valid_until": "2020-01-01"}, 400, "CONFORMITY_DOC_EXPIRED"),
    ],
)
def test_serial_receipt_needs_numbers_and_the_document(world, classes, line, status, code):
    order_id, ids = _order(world, [{"product_id": world["rail"].pk, "quantity": 2}])
    body = _serial_line(ids[world["rail"].pk], line.pop("serials"), quantity=line.pop("quantity", 2), **line)
    response = _receive(world, order_id, [body])
    assert response.status_code == status, response.json()
    assert response.json()["detail"] == code
    assert not TraceUnit.objects.exists()
    assert not StockBalance.objects.filter(product=world["rail"]).exists(), "отказ — остаток не тронут"


def test_serial_receipt_records_each_unit_and_the_document(world, classes):
    order_id, ids = _order(world, [{"product_id": world["rail"].pk, "quantity": 2}])
    response = _receive(world, order_id, [_serial_line(ids[world["rail"].pk], ["ENG-1", "ENG-2"])])
    assert response.status_code == 200, response.json()
    units = TraceUnit.objects.filter(product=world["rail"]).order_by("number")
    assert [(u.kind, u.number, u.quantity, u.status) for u in units] == [
        ("serial", "ENG-1", 1, TraceStatus.IN_STOCK),
        ("serial", "ENG-2", 1, TraceStatus.IN_STOCK),
    ]
    line = GoodsReceiptLine.objects.get()
    assert line.conformity_doc_number == "СЕРТ-0001" and line.conformity_doc_valid_until
    [receipt] = response.json()["receipts"]
    assert receipt["lines"][0]["units"] == ["ENG-1", "ENG-2"]
    assert receipt["lines"][0]["doc_number"] == "СЕРТ-0001"


def test_a_serial_already_received_is_refused(world, classes):
    first, ids = _order(world, [{"product_id": world["rail"].pk, "quantity": 1}])
    assert _receive(world, first, [_serial_line(ids[world["rail"].pk], ["ENG-9"])]).status_code == 200
    second, ids = _order(world, [{"product_id": world["rail"].pk, "quantity": 1}])
    refused = _receive(world, second, [_serial_line(ids[world["rail"].pk], ["ENG-9"])])
    assert refused.status_code == 409
    assert refused.json() == {"detail": "SERIAL_EXISTS", "number": "ENG-9"}


def test_lot_receipt_needs_a_lot_and_keeps_the_expiry(world, classes):
    order_id, ids = _order(world, [{"product_id": world["bolt"].pk, "quantity": 5}])
    line = ids[world["bolt"].pk]
    assert _receive(world, order_id, [{"order_line_id": line, "quantity": 5}]).json()["detail"] == "LOT_REQUIRED"
    ok = _receive(world, order_id, [{"order_line_id": line, "quantity": 5, "lot": "L-1", "expiry_date": _future(30)}])
    assert ok.status_code == 200, ok.json()
    unit = TraceUnit.objects.get()
    assert (unit.kind, unit.number, unit.quantity) == ("lot", "L-1", 5)
    assert unit.expiry_date == timezone.localdate() + timedelta(days=30)


def test_quantity_only_product_changes_nothing(world, classes):
    world["bolt"].category = classes["plain"]
    world["bolt"].save(update_fields=["category"])
    order_id, ids = _order(world, [{"product_id": world["bolt"].pk, "quantity": 3}])
    pending = api(world["supply"]).get(f"{STOCK}receipts/").json()["pending"]
    assert (pending[0]["tracking"], pending[0]["requires_doc"]) == ("none", False)
    body = {"order_line_id": ids[world["bolt"].pk], "quantity": 3, "serials": ["лишнее"]}
    assert _receive(world, order_id, [body]).status_code == 200
    assert not TraceUnit.objects.exists(), "для N номера не ведутся"


def test_pending_receipt_says_what_to_ask(world, classes):
    _order(world, [{"product_id": world["rail"].pk, "quantity": 1}, {"product_id": world["bolt"].pk, "quantity": 1}])
    pending = {row["name"]: row for row in api(world["supply"]).get(f"{STOCK}receipts/").json()["pending"]}
    assert (pending[world["rail"].name]["tracking"], pending[world["rail"].name]["requires_doc"]) == ("serial", True)
    assert (pending[world["bolt"].name]["tracking"], pending[world["bolt"].name]["requires_doc"]) == ("lot", False)


# ── отгрузка ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_shipping_tracked_goods_needs_free_units(world, classes):
    deal = _project(world)
    rows = _reservations(world, deal)
    rail, bolt = rows[world["rail"].pk], rows[world["bolt"].pk]
    assert rail["tracking"] == "serial" and [u["number"] for u in rail["units"]] == ["ENG-0001", "ENG-0002"]
    assert bolt["tracking"] == "lot" and [(u["number"], u["available"]) for u in bolt["units"]] == [("LOT-77", 5)]

    no_units = _ship(world, deal, [{"reservation_id": rail["id"], "quantity": 1}])
    assert no_units.status_code == 400 and no_units.json()["detail"] == "UNITS_REQUIRED"
    too_few = _ship(
        world, deal, [{"reservation_id": rail["id"], "quantity": 2, "units": [{"unit_id": rail["units"][0]["id"]}]}]
    )
    assert too_few.json()["detail"] == "UNITS_COUNT_MISMATCH"
    foreign = _ship(
        world, deal, [{"reservation_id": rail["id"], "quantity": 1, "units": [{"unit_id": bolt["units"][0]["id"]}]}]
    )
    assert foreign.status_code == 404 and foreign.json()["detail"] == "UNIT_NOT_FOUND"

    first = rail["units"][0]["id"]
    shipped = _ship(
        world,
        deal,
        [
            {"reservation_id": rail["id"], "quantity": 1, "units": [{"unit_id": first}]},
            {
                "reservation_id": bolt["id"],
                "quantity": 3,
                "units": [{"unit_id": bolt["units"][0]["id"], "quantity": 3}],
            },
        ],
    )
    assert shipped.status_code == 201, shipped.json()
    assert [line["units"] for line in shipped.json()["lines"]] == [
        [{"number": "ENG-0001", "quantity": 1}],
        [{"number": "LOT-77", "quantity": 3}],
    ]
    assert TraceUnit.objects.get(pk=first).status == TraceStatus.SHIPPED
    lot = TraceUnit.objects.get(number="LOT-77")
    assert (lot.shipped_quantity, lot.status) == (3, TraceStatus.IN_STOCK), "партия ушла не вся"

    again = _ship(world, deal, [{"reservation_id": rail["id"], "quantity": 1, "units": [{"unit_id": first}]}])
    assert again.status_code == 409 and again.json()["detail"] == "UNIT_NOT_AVAILABLE", "отгружают только свободные"
    left = _reservations(world, deal)
    assert [u["number"] for u in left[world["rail"].pk]["units"]] == ["ENG-0002"]
    assert left[world["bolt"].pk]["units"][0]["available"] == 2


def test_lot_over_its_remaining_is_refused(world, classes):
    deal = _project(world, rail=1, bolt=5)
    bolt = _reservations(world, deal)[world["bolt"].pk]
    lot = bolt["units"][0]["id"]
    assert (
        _ship(
            world, deal, [{"reservation_id": bolt["id"], "quantity": 4, "units": [{"unit_id": lot, "quantity": 4}]}]
        ).status_code
        == 201
    )
    over = _ship(
        world, deal, [{"reservation_id": bolt["id"], "quantity": 1, "units": [{"unit_id": lot, "quantity": 2}]}]
    )
    assert over.status_code == 409 and over.json() == {"detail": "UNIT_NOT_AVAILABLE", "number": "LOT-77", "max": 1}
    last = _ship(
        world, deal, [{"reservation_id": bolt["id"], "quantity": 1, "units": [{"unit_id": lot, "quantity": 1}]}]
    )
    assert last.status_code == 201
    assert TraceUnit.objects.get(pk=lot).status == TraceStatus.SHIPPED


# ── поиск: откуда и куда ───────────────────────────────────────────────────────────────────────────────────────────


def test_search_by_serial_shows_where_it_came_from_and_where_it_went(world, classes):
    deal = _project(world)
    rail = _reservations(world, deal)[world["rail"].pk]
    unit = next(u for u in rail["units"] if u["number"] == "ENG-0002")
    shipped = _ship(world, deal, [{"reservation_id": rail["id"], "quantity": 1, "units": [{"unit_id": unit["id"]}]}])
    assert shipped.status_code == 201

    found = api(world["reader"]).get(f"{STOCK}trace/", {"q": "eng-0002"})
    assert found.status_code == 200
    [row] = found.json()["results"]
    assert (row["kind"], row["number"], row["status"]) == ("serial", "ENG-0002", "shipped")
    origin = row["origin"]
    assert origin["supplier_name"] == world["vendor"].name and origin["order_number"].startswith("PO-")
    assert origin["manufacturer"] == "Завод Вымышленный" and origin["doc_number"] == "СЕРТ-0001"
    assert origin["deal"]["id"] == deal.pk
    [dest] = row["destinations"]
    assert dest["shipment_number"] == shipped.json()["number"] and dest["quantity"] == 1
    assert dest["deal"] == {"id": deal.pk, "number": deal.number or None, "client_name": world["client"].name}

    partial = api(world["reader"]).get(f"{STOCK}trace/", {"q": "ENG-000"}).json()["results"]
    assert [r["number"] for r in partial] == ["ENG-0001", "ENG-0002"]
    assert api(world["reader"]).get(f"{STOCK}trace/", {"q": "E"}).json()["results"] == [], "от 2 знаков"
    lot = api(world["reader"]).get(f"{STOCK}trace/", {"q": "LOT-77"}).json()["results"]
    assert lot[0]["kind"] == "lot" and lot[0]["destinations"] == []
    assert api(world["outsider"]).get(f"{STOCK}trace/", {"q": "ENG"}).status_code == 403


# ── строка ЗП ↔ цена поставщика ────────────────────────────────────────────────────────────────────────────────────


def test_order_line_keeps_the_supplier_price_it_came_from(world, classes):
    fca = DeliveryBasis.objects.get_or_create(code="FCA", defaults={"name": "FCA", "sort_order": 10})[0]
    currency = Currency.objects.get(code="UZS")
    valid = timezone.localdate() + timedelta(days=60)
    offer = SupplierOffer.objects.create(
        product=world["rail"],
        supplier=world["vendor"],
        base_price=Decimal("10"),
        currency=currency,
        delivery_basis=fca,
        valid_until=valid,
    )
    SupplierOffer.objects.create(
        product=world["bolt"],
        supplier=world["vendor"],
        base_price=Decimal("1"),
        currency=currency,
        valid_until=timezone.localdate() - timedelta(days=1),
    )
    created = api(world["supply"]).post(
        f"{STOCK}orders/",
        {
            "supplier_id": world["vendor"].pk,
            "lines": [{"product_id": world["rail"].pk, "quantity": 1}, {"product_id": world["bolt"].pk, "quantity": 1}],
        },
        format="json",
    )
    assert created.status_code == 201
    detail = api(world["supply"]).get(f"{STOCK}orders/{created.json()['id']}/").json()
    lines = {line["product_id"]: line for line in detail["lines"]}
    assert lines[world["rail"].pk]["offer"] == {
        "id": offer.pk,
        "incoterms": "FCA",
        "valid_until": valid.isoformat(),
        "expired": False,
    }
    assert lines[world["bolt"].pk]["offer"] is None, "просроченная цена не подставляется"
    assert (lines[world["rail"].pk]["tracking"], lines[world["rail"].pk]["requires_doc"]) == ("serial", True)


# ── миграции вперёд и назад ─────────────────────────────────────────────────────────────────────────────────────────


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)


def test_migrations_roll_back_and_forward():
    before = [
        ("inventory", "0001_d2_2_stock_and_procurement"),
        ("supply", "0002_overdue_orders_beat"),
        ("catalog", "0008_cat1_supplier_prices"),
    ]
    after = [
        ("catalog", "0009_category_tracking"),
        ("supply", "0003_goodsreceiptline_conformity_doc_number_and_more"),
        ("inventory", "0002_traceunit_traceallocation_and_more"),
    ]
    _migrate(before)
    tables = connection.introspection.table_names()
    assert "inventory_traceunit" not in tables and "inventory_traceallocation" not in tables
    _migrate(after)
    tables = connection.introspection.table_names()
    assert "inventory_traceunit" in tables and "inventory_traceallocation" in tables
