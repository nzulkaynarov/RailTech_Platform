"""D2-2: «Склад» — живые ответы `/api/v1/stock/*` совпадают с выгрузкой OpenAPI (сторож по образцу D2-0).

Каждая операция склада и закупок вызывается так, как её вызывает BFF Платформы (`apps/platform/bff`), и ответ — успешный и
отказной (403, 404, 409, 400) — сверяется со схемой операции: статус описан, тело подходит, лишних полей нет, поля тела
запроса есть в схеме запроса.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from inventory.tests.support import api, make_deal, make_world

from core.tests.openapi_fixtures import conforms, sends

pytestmark = pytest.mark.django_db

S = "/api/v1/stock/"


@pytest.fixture
def world(db):
    return make_world()


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


def _call(client, method, template, path, body=None, *, status, **query):
    response = (
        getattr(client, method)(path, body, format="json")
        if body is not None
        else getattr(client, method)(path, query or None)
    )
    if body is not None:
        sends(template, method, body)
    conforms(response, template, method, status=status)
    return response


def test_stock_balances_reservations_adjustments_and_shipments_conform(world):
    supply, reader, outsider = api(world["supply"]), api(world["reader"]), api(world["outsider"])
    adjust = {"product_id": world["rail"].pk, "quantity": 8, "cell": "A-01", "note": "Начальный остаток"}
    _call(supply, "post", f"{S}adjustments/", f"{S}adjustments/", adjust, status=200)
    _call(
        supply,
        "post",
        f"{S}adjustments/",
        f"{S}adjustments/",
        {"product_id": world["rail"].pk, "quantity": -100},
        status=409,
    )
    _call(
        supply,
        "post",
        f"{S}adjustments/",
        f"{S}adjustments/",
        {"product_id": world["rail"].pk, "quantity": 0},
        status=400,
    )
    _call(reader, "post", f"{S}adjustments/", f"{S}adjustments/", adjust, status=403)

    _call(reader, "get", f"{S}balances/", f"{S}balances/", status=200)
    _call(reader, "get", f"{S}balances/", f"{S}balances/", status=200, q="стрелочный", only="reserved")
    _call(outsider, "get", f"{S}balances/", f"{S}balances/", status=403)
    _call(reader, "get", f"{S}balances/{{product_id}}/", f"{S}balances/{world['rail'].pk}/", status=200)
    _call(reader, "get", f"{S}balances/{{product_id}}/", f"{S}balances/999999/", status=404)

    deal, _q, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    reserve = {"deal_id": deal.pk, "quote_item_id": item.pk, "quantity": 4}
    created = _call(supply, "post", f"{S}reservations/", f"{S}reservations/", reserve, status=201)
    _call(supply, "post", f"{S}reservations/", f"{S}reservations/", {**reserve, "quantity": 99}, status=400)
    _call(supply, "post", f"{S}reservations/", f"{S}reservations/", {**reserve, "quote_item_id": 999999}, status=404)
    _call(reader, "post", f"{S}reservations/", f"{S}reservations/", reserve, status=403)
    _call(reader, "get", f"{S}reservations/", f"{S}reservations/", status=200, deal_id=deal.pk)

    ship = {
        "deal_id": deal.pk,
        "lines": [{"reservation_id": created.json()["id"], "quantity": 4}],
        "tracking": "TRK-9",
        "carrier": "ООО Перевозка",
        "note": "Вымышленная",
    }
    _call(api(world["shipper"]), "post", f"{S}shipments/", f"{S}shipments/", ship, status=201)
    _call(api(world["shipper"]), "post", f"{S}shipments/", f"{S}shipments/", ship, status=409)
    _call(reader, "post", f"{S}shipments/", f"{S}shipments/", ship, status=403)
    _call(reader, "get", f"{S}shipments/", f"{S}shipments/", status=200, deal_id=deal.pk)

    other, _q2, (other_item,) = make_deal(world, [(world["bolt"], 1)])
    _call(
        supply,
        "post",
        f"{S}adjustments/",
        f"{S}adjustments/",
        {"product_id": world["bolt"].pk, "quantity": 1},
        status=200,
    )
    other_reservation = _call(
        supply,
        "post",
        f"{S}reservations/",
        f"{S}reservations/",
        {"deal_id": other.pk, "quote_item_id": other_item.pk, "quantity": 1},
        status=201,
    )
    _call(
        supply,
        "delete",
        f"{S}reservations/{{reservation_id}}/",
        f"{S}reservations/{other_reservation.json()['id']}/",
        status=200,
    )
    _call(
        supply,
        "delete",
        f"{S}reservations/{{reservation_id}}/",
        f"{S}reservations/{other_reservation.json()['id']}/",
        status=409,
    )
    _call(
        reader,
        "delete",
        f"{S}reservations/{{reservation_id}}/",
        f"{S}reservations/{other_reservation.json()['id']}/",
        status=403,
    )
    _call(supply, "delete", f"{S}reservations/{{reservation_id}}/", f"{S}reservations/999999/", status=404)
    _call(reader, "get", f"{S}suppliers/", f"{S}suppliers/", status=200, q="Вымышленный")
    _call(outsider, "get", f"{S}suppliers/", f"{S}suppliers/", status=403)


def test_orders_receipts_overdue_and_price_requests_conform(world):
    supply, reader, outsider = api(world["supply"]), api(world["reader"]), api(world["outsider"])
    deal, _q, (item,) = make_deal(world, [(world["rail"], 3)])
    new = {
        "supplier_id": world["vendor"].pk,
        "expected_date": (timezone.localdate() - timedelta(days=2)).isoformat(),
        "note": "Срочно",
        "currency": "UZS",
        "lines": [
            {
                "product_id": world["rail"].pk,
                "quantity": 5,
                "unit_price": "90000.00",
                "deal_id": deal.pk,
                "quote_item_id": item.pk,
            }
        ],
    }
    created = _call(supply, "post", f"{S}orders/", f"{S}orders/", new, status=201)
    order_id = created.json()["id"]
    _call(supply, "post", f"{S}orders/", f"{S}orders/", {**new, "lines": []}, status=400)
    _call(supply, "post", f"{S}orders/", f"{S}orders/", {**new, "supplier_id": world["client"].pk}, status=404)
    _call(reader, "post", f"{S}orders/", f"{S}orders/", new, status=403)
    for who in (supply, reader):
        _call(who, "get", f"{S}orders/", f"{S}orders/", status=200)
    _call(
        reader,
        "get",
        f"{S}orders/",
        f"{S}orders/",
        status=200,
        q="стрелочный",
        overdue="1",
        number=created.json()["number"],
    )
    _call(outsider, "get", f"{S}orders/", f"{S}orders/", status=403)
    _call(reader, "get", f"{S}orders/{{order_id}}/", f"{S}orders/{order_id}/", status=200)
    _call(reader, "get", f"{S}orders/{{order_id}}/", f"{S}orders/999999/", status=404)

    line_id = created.json()["lines"][0]["id"]
    patch = {"note": "Срочно!", "lines": [{"id": line_id, "product_id": world["rail"].pk, "quantity": 5}]}
    _call(supply, "patch", f"{S}orders/{{order_id}}/", f"{S}orders/{order_id}/", patch, status=200)
    _call(reader, "patch", f"{S}orders/{{order_id}}/", f"{S}orders/{order_id}/", {"note": "x"}, status=403)
    _call(supply, "post", f"{S}orders/{{order_id}}/confirm/", f"{S}orders/{order_id}/confirm/", {}, status=409)
    _call(supply, "post", f"{S}orders/{{order_id}}/send/", f"{S}orders/{order_id}/send/", {"to_email": ""}, status=200)
    _call(
        supply,
        "patch",
        f"{S}orders/{{order_id}}/",
        f"{S}orders/{order_id}/",
        {"note": "x", "lines": patch["lines"]},
        status=409,
    )
    _call(reader, "post", f"{S}orders/{{order_id}}/send/", f"{S}orders/{order_id}/send/", {}, status=403)
    _call(
        supply,
        "post",
        f"{S}orders/{{order_id}}/confirm/",
        f"{S}orders/{order_id}/confirm/",
        {"expected_date": (timezone.localdate() - timedelta(days=2)).isoformat()},
        status=200,
    )

    _call(reader, "get", f"{S}overdue/", f"{S}overdue/", status=403)
    overdue = _call(supply, "get", f"{S}overdue/", f"{S}overdue/", status=200)
    assert [row["number"] for row in overdue.json()["results"]] == [created.json()["number"]]
    _call(reader, "get", f"{S}receipts/", f"{S}receipts/", status=200)
    _call(outsider, "get", f"{S}receipts/", f"{S}receipts/", status=403)

    receipt = {
        "lines": [{"order_line_id": line_id, "quantity": 2, "cell": "B-01"}],
        "supplier_doc": "НП-1",
        "note": "Часть",
    }
    _call(supply, "post", f"{S}orders/{{order_id}}/receipts/", f"{S}orders/{order_id}/receipts/", receipt, status=200)
    _call(
        supply,
        "post",
        f"{S}orders/{{order_id}}/receipts/",
        f"{S}orders/{order_id}/receipts/",
        {"lines": [{"order_line_id": line_id, "quantity": 9}]},
        status=400,
    )
    _call(
        supply,
        "post",
        f"{S}orders/{{order_id}}/receipts/",
        f"{S}orders/{order_id}/receipts/",
        {"lines": [{"order_line_id": 999999, "quantity": 1}]},
        status=404,
    )
    _call(reader, "post", f"{S}orders/{{order_id}}/receipts/", f"{S}orders/{order_id}/receipts/", receipt, status=403)
    _call(
        supply, "post", f"{S}orders/{{order_id}}/cancel/", f"{S}orders/{order_id}/cancel/", {"reason": "x"}, status=409
    )

    second = _call(
        supply,
        "post",
        f"{S}orders/",
        f"{S}orders/",
        {"supplier_id": world["vendor"].pk, "lines": [{"product_id": world["bolt"].pk, "quantity": 1}]},
        status=201,
    )
    _call(
        supply,
        "post",
        f"{S}orders/{{order_id}}/cancel/",
        f"{S}orders/{second.json()['id']}/cancel/",
        {"reason": "Передумали"},
        status=200,
    )
    _call(reader, "post", f"{S}orders/{{order_id}}/cancel/", f"{S}orders/{second.json()['id']}/cancel/", {}, status=403)
    _call(
        supply,
        "post",
        f"{S}orders/from-deal/",
        f"{S}orders/from-deal/",
        {"deal_id": deal.pk, "supplier_id": world["vendor"].pk},
        status=409,
    )
    _call(
        supply,
        "post",
        f"{S}orders/from-deal/",
        f"{S}orders/from-deal/",
        {"deal_id": 999999, "supplier_id": world["vendor"].pk},
        status=404,
    )
    _call(
        reader,
        "post",
        f"{S}orders/from-deal/",
        f"{S}orders/from-deal/",
        {"deal_id": deal.pk, "supplier_id": world["vendor"].pk},
        status=403,
    )

    request = {
        "deal_id": deal.pk,
        "supplier_id": world["vendor"].pk,
        "line_ids": [item.pk],
        "note": "Срочно",
        "to_email": "",
    }
    asked = _call(supply, "post", f"{S}price-requests/", f"{S}price-requests/", request, status=201)
    _call(
        supply,
        "post",
        f"{S}price-requests/",
        f"{S}price-requests/",
        {**request, "supplier_id": world["silent"].pk},
        status=409,
    )
    _call(supply, "post", f"{S}price-requests/", f"{S}price-requests/", {**request, "line_ids": []}, status=400)
    _call(reader, "post", f"{S}price-requests/", f"{S}price-requests/", request, status=403)
    _call(reader, "get", f"{S}price-requests/", f"{S}price-requests/", status=200, deal_id=deal.pk)
    _call(outsider, "get", f"{S}price-requests/", f"{S}price-requests/", status=403)
    answer_path = f"{S}price-requests/{asked.json()['id']}/answer/"
    _call(supply, "post", f"{S}price-requests/{{request_id}}/answer/", answer_path, {"note": "90 млн"}, status=200)
    _call(supply, "post", f"{S}price-requests/{{request_id}}/answer/", answer_path, {"note": ""}, status=409)
    _call(reader, "post", f"{S}price-requests/{{request_id}}/answer/", answer_path, {"note": ""}, status=403)
    _call(
        supply,
        "post",
        f"{S}price-requests/{{request_id}}/answer/",
        f"{S}price-requests/999999/answer/",
        {"note": ""},
        status=404,
    )


def test_tracked_receipt_shipment_and_trace_search_conform(world):
    """L0-3 (ADR-0021): приёмка с серийными и документом, отгрузка с выбором единиц, поиск по номеру."""
    from catalog.models import Category

    world["rail"].category = Category.objects.create(name="Серийные", tracking="serial", requires_conformity_doc=True)
    world["rail"].save(update_fields=["category"])
    supply, reader = api(world["supply"]), api(world["reader"])
    deal, _q, (item,) = make_deal(world, [(world["rail"], 1)], approved=True, signed=True)
    line = {"product_id": world["rail"].pk, "quantity": 1, "deal_id": deal.pk, "quote_item_id": item.pk}
    order = supply.post(f"{S}orders/", {"supplier_id": world["vendor"].pk, "lines": [line]}, format="json").json()
    supply.post(f"{S}orders/{order['id']}/send/", {}, format="json")
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    supply.post(f"{S}orders/{order['id']}/confirm/", {"expected_date": tomorrow}, format="json")
    _call(reader, "get", f"{S}receipts/", f"{S}receipts/", status=200)
    order_line = supply.get(f"{S}orders/{order['id']}/").json()["lines"][0]["id"]
    template = f"{S}orders/{{order_id}}/receipts/"
    url = f"{S}orders/{order['id']}/receipts/"
    receipt = {
        "lines": [
            {
                "order_line_id": order_line,
                "quantity": 1,
                "serials": ["SN-1"],
                "lot": "",
                "expiry_date": None,
                "doc_number": "ДС-1",
                "doc_valid_until": (timezone.localdate() + timedelta(days=90)).isoformat(),
            }
        ]
    }
    _call(supply, "post", template, url, {"lines": [{**receipt["lines"][0], "serials": []}]}, status=400)
    _call(supply, "post", template, url, receipt, status=200)

    reservation = _call(reader, "get", f"{S}reservations/", f"{S}reservations/", status=200, deal_id=deal.pk)
    row = reservation.json()["results"][0]
    ship = {"deal_id": deal.pk, "lines": [{"reservation_id": row["id"], "quantity": 1}]}
    shipper = api(world["shipper"])
    _call(shipper, "post", f"{S}shipments/", f"{S}shipments/", ship, status=400)
    picked = {**ship, "lines": [{**ship["lines"][0], "units": [{"unit_id": row["units"][0]["id"], "quantity": 1}]}]}
    _call(shipper, "post", f"{S}shipments/", f"{S}shipments/", picked, status=201)
    _call(shipper, "post", f"{S}shipments/", f"{S}shipments/", picked, status=409)
    _call(reader, "get", f"{S}trace/", f"{S}trace/", status=200, q="SN-1")
    _call(api(world["outsider"]), "get", f"{S}trace/", f"{S}trace/", status=403, q="SN-1")
