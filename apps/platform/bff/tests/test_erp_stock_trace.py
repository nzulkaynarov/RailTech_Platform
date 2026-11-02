"""Прослеживаемость (L0-3, ADR-0021): серийные и партии в приёмке и отгрузке, поиск, цена ЗП.

ERP — на respx, ответы BFF — по схемам platform-bff.yaml. BFF не решает: класс учёта, обязательность
номеров, число серийных и свободные единицы проверяет ERP. Здесь — поля передаются в ERP как ввели,
id единиц — строками, номера заказов и проектов вместо внутренних id, раздел `erp.stock` (поиск —
чтение).
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.test_erp_calc import CALC, deal, refs
from tests.test_erp_stock import (
    NUMBER,
    ORDER,
    ORDER_ENCODED,
    STOCK,
    call,
    order_detail,
    order_row,
    ref,
    reservation,
)


@pytest.fixture
def erp(be: Backends) -> respx.MockRouter:
    """ERP: заявка найдена в лёгком справочнике (как в `test_erp_stock`)."""
    be.router.get(f"{CALC}/deals/").mock(return_value=httpx.Response(200, json=refs(deal())))
    rights = {"manage": True, "ship": True, "prices": True}
    be.router.get(f"{STOCK}/orders/").mock(
        return_value=httpx.Response(200, json={"results": [order_row()], "rights": rights})
    )
    return be.router


def traced_unit(**extra: Any) -> dict[str, Any]:
    return {
        "id": 501,
        "kind": "serial",
        "number": "ENG-0002",
        "expiry_date": None,
        "available": 0,
        "quantity": 1,
        "shipped_quantity": 1,
        "status": "shipped",
        "product": {"id": 3, "name": "Двигатель тяговый", "article": "ДТ-1"},
        "origin": {
            "receipt_id": 9,
            "received_at": "2026-10-25T09:00:00+00:00",
            "supplier_doc": "НП-77",
            "order_id": 31,
            "order_number": ORDER,
            "supplier_name": "ООО Вымышленный Поставщик",
            "manufacturer": "Завод Вымышленный",
            "doc_number": "СЕРТ-0001",
            "doc_valid_until": "2027-10-01",
            "deal": ref(),
        },
        "destinations": [
            {
                "shipment_id": 12,
                "shipment_number": "ОТГ-2026-014",
                "shipped_at": "2026-10-28T09:00:00+00:00",
                "quantity": 1,
                "deal": ref(number="ПР-2026-104"),
            }
        ],
        **extra,
    }


async def test_search_shows_origin_and_destinations(
    web: Web,
    erp: respx.MockRouter,
    check: ContractChecker,
) -> None:
    await web.login(["MANAGER"])  # «Склад» — чтение: поиск доступен
    route = erp.get(f"{STOCK}/trace/").mock(
        return_value=httpx.Response(200, json={"results": [traced_unit()]})
    )
    found = await web.client.get("/api/v1/erp/stock/trace", params={"q": "  ENG-0002 "})
    check(found, "/erp/stock/trace", "get")
    assert dict(route.calls.last.request.url.params) == {"q": "ENG-0002"}
    [unit] = found.json()["items"]
    assert unit["id"] == "501"
    assert unit["product"]["id"] == "3"
    assert unit["origin"]["order_path"] == f"/erp/stock/{ORDER_ENCODED}"
    assert unit["origin"]["supplier"] == "ООО Вымышленный Поставщик"
    assert unit["origin"]["request"]["number"] == NUMBER
    assert unit["destinations"][0]["request"]["path"] == "/eds/projects/%D0%9F%D0%A0-2026-104"
    assert "receipt_id" not in unit["origin"]
    assert "order_id" not in unit["origin"]


async def test_search_needs_a_query_and_the_section(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get("/api/v1/erp/stock/trace")).status_code == 422
    await web.login(["ADMIN"])
    assert (await web.client.get("/api/v1/erp/stock/trace", params={"q": "ENG"})).status_code == 403


async def test_receipt_passes_serials_lot_and_document(
    web: Web,
    erp: respx.MockRouter,
    check: ContractChecker,
) -> None:
    await web.login(["SUPPLY"])
    detail = order_detail()
    detail["lines"][0].update(
        offer={"id": 4, "incoterms": "FCA", "valid_until": "2026-12-31", "expired": False},
        tracking="serial",
        requires_doc=True,
    )
    detail["receipts"][0]["lines"][0].update(
        units=["ENG-1", "ENG-2"],
        expiry_date=None,
        doc_number="СЕРТ-1",
        doc_valid_until="2027-01-01",
    )
    post = erp.post(f"{STOCK}/orders/31/receipts/").mock(
        return_value=httpx.Response(200, json=detail)
    )
    body = {
        "lines": [
            {
                "order_line_id": "77",
                "quantity": 2,
                "serials": ["ENG-1", "ENG-2"],
                "doc_number": "СЕРТ-1",
                "doc_valid_until": "2027-01-01",
            },
            {"order_line_id": "78", "quantity": 5, "lot": "L-7", "expiry_date": "2027-03-01"},
        ]
    }
    received = await call(web, "POST", f"/erp/stock/orders/{ORDER}/receipts", body)
    check(received, "/erp/stock/orders/{order_number}/receipts", "post")
    assert json.loads(post.calls.last.request.content)["lines"] == [
        {
            "order_line_id": 77,
            "quantity": 2,
            "cell": "",
            "serials": ["ENG-1", "ENG-2"],
            "doc_number": "СЕРТ-1",
            "doc_valid_until": "2027-01-01",
        },
        {"order_line_id": 78, "quantity": 5, "cell": "", "lot": "L-7", "expiry_date": "2027-03-01"},
    ]
    line = received.json()["lines"][0]
    assert line["offer"] == {"incoterms": "FCA", "valid_until": "2026-12-31", "expired": False}
    assert (line["tracking"], line["requires_doc"]) == ("serial", True)
    assert received.json()["receipts"][0]["lines"][0]["units"] == ["ENG-1", "ENG-2"]


async def test_erp_refusals_on_numbers_are_translated(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["SUPPLY"])
    post = erp.post(f"{STOCK}/orders/31/receipts/").mock(
        return_value=httpx.Response(409, json={"detail": "SERIAL_EXISTS", "number": "ENG-1"})
    )
    body = {"lines": [{"order_line_id": "77", "quantity": 1, "serials": ["ENG-1"]}]}
    refused = await call(web, "POST", f"/erp/stock/orders/{ORDER}/receipts", body)
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "serial_exists"
    post.mock(
        return_value=httpx.Response(400, json={"detail": "SERIALS_COUNT_MISMATCH", "expected": 2})
    )
    short = await call(web, "POST", f"/erp/stock/orders/{ORDER}/receipts", body)
    assert short.status_code == 422


async def test_reservations_carry_free_units_and_ship_sends_the_picks(
    web: Web,
    erp: respx.MockRouter,
    check: ContractChecker,
) -> None:
    await web.login(["SUPPLY"])
    unit = {"id": 501, "kind": "serial", "number": "ENG-1", "expiry_date": None, "available": 1}
    erp.get(f"{STOCK}/reservations/").mock(
        return_value=httpx.Response(
            200, json={"results": [reservation(tracking="serial", units=[unit])]}
        )
    )
    listed = await web.client.get("/api/v1/erp/stock/reservations", params={"request": NUMBER})
    check(listed, "/erp/stock/reservations", "get")
    row = listed.json()["items"][0]
    assert row["tracking"] == "serial"
    assert row["units"] == [{**unit, "id": "501"}]

    shipment = {
        "id": 12,
        "number": "ОТГ-2026-014",
        "deal": ref(number="ПР-2026-104"),
        "tracking": None,
        "carrier": None,
        "note": None,
        "shipped_at": "2026-10-28T09:00:00+00:00",
        "shipped_by_name": "Демо",
        "lines": [
            {
                "product_id": 3,
                "name": "Двигатель",
                "quantity": 1,
                "cell": None,
                "units": [{"number": "ENG-1", "quantity": 1}],
            }
        ],
    }
    create = erp.post(f"{STOCK}/shipments/").mock(return_value=httpx.Response(201, json=shipment))
    body = {
        "request": NUMBER,
        "lines": [{"reservation_id": "41", "quantity": 1, "units": [{"unit_id": "501"}]}],
    }
    created = await call(web, "POST", "/erp/stock/shipments", body)
    check(created, "/erp/stock/shipments", "post")
    assert json.loads(create.calls.last.request.content)["lines"] == [
        {"reservation_id": 41, "quantity": 1, "units": [{"unit_id": 501, "quantity": 1}]}
    ]
    assert created.json()["lines"][0]["units"] == [{"number": "ENG-1", "quantity": 1}]
    create.mock(return_value=httpx.Response(400, json={"detail": "UNITS_REQUIRED", "expected": 1}))
    bare = {"request": NUMBER, "lines": [{"reservation_id": "41", "quantity": 1}]}
    refused = await call(web, "POST", "/erp/stock/shipments", bare)
    assert refused.status_code == 422
    assert refused.json()["details"]["reason"] == "units_required"
