"""Склад и закупки (D2-2, контракт 0.27.0, теги `stock` и `calc`): `/erp/stock*` и
`/erp/calc/{номер}/…reserve|price-requests` поверх ERP `/api/v1/stock/*`.

ERP — на respx; ответы BFF сверяются со схемами platform-bff.yaml. Остаток, резерв, переходы
статусов, приёмку и отгрузку решает ERP: здесь проверяются доступ к разделам каталога (403 до ERP),
оркестрация (заявка и заказ ищутся по бизнес-номеру, резерв строки — два вызова ERP), вырезание цен
поставщиков, перевод ошибок ERP, вид очереди `supplier_overdue` и уведомление.
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.feeds_support import FeedBackends, Moments, notification
from tests.test_erp_calc import CALC, ENCODED, NUMBER, deal, line, refs, sheet

API = f"{ERP_URL}/api/v1"
STOCK = f"{API}/stock"
ORDER = "ЗП-2026-031"
ORDER_ENCODED = "%D0%97%D0%9F-2026-031"


def ref(**extra: Any) -> dict[str, Any]:
    return {"id": 104, "number": NUMBER, "client_name": "ООО Пример Логистик", **extra}


def order_row(**extra: Any) -> dict[str, Any]:
    return {
        "id": 31,
        "number": ORDER,
        "status": "confirmed",
        "supplier": {"id": 5, "name": "ООО Вымышленный Поставщик"},
        "expected_date": "2026-11-20",
        "overdue": False,
        "days_overdue": None,
        "currency": "UZS",
        "lines_count": 1,
        "quantity": 10,
        "received_quantity": 4,
        "receipt_state": "partial",
        "total": "900000.00",
        "projects": [ref()],
        "created_at": "2026-10-20T09:00:00+00:00",
        "created_by_name": "Демо Снабженцев",
        "actions": {
            "edit": False,
            "send": False,
            "confirm": False,
            "receive": True,
            "cancel": False,
        },
        **extra,
    }


def order_detail(**extra: Any) -> dict[str, Any]:
    return {
        **order_row(),
        "supplier": {"id": 5, "name": "ООО Вымышленный Поставщик", "email": "sales@vendor.example"},
        "note": "",
        "sent_at": "2026-10-21T09:00:00+00:00",
        "sent_to": "sales@vendor.example",
        "confirmed_at": "2026-10-22T09:00:00+00:00",
        "received_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "lines": [
            {
                "id": 77,
                "position": 1,
                "product_id": 3,
                "name": "Перевод стрелочный Р65 1/11",
                "article": "СП-Р65-11",
                "unit": "шт.",
                "quantity": 10,
                "received_quantity": 4,
                "unit_price": "90000.00",
                "line_total": "900000.00",
                "deal": ref(),
                "quote_item_id": 7,
            }
        ],
        "receipts": [
            {
                "id": 9,
                "received_at": "2026-10-25T09:00:00+00:00",
                "received_by_name": "Демо Снабженцев",
                "supplier_doc": "НП-77",
                "note": None,
                "lines": [
                    {
                        "order_line_id": 77,
                        "name": "Перевод стрелочный Р65 1/11",
                        "quantity": 4,
                        "cell": "B-02",
                    }
                ],
            }
        ],
        "log": [
            {
                "kind": "created",
                "at": "2026-10-20T09:00:00+00:00",
                "by_name": "Демо Снабженцев",
                "detail": None,
            }
        ],
        "rights": {"manage": True, "ship": True, "prices": True},
        **extra,
    }


def stock_row(**extra: Any) -> dict[str, Any]:
    return {
        "product_id": 3,
        "name": "Перевод стрелочный Р65 1/11",
        "article": "СП-Р65-11",
        "unit": "шт.",
        "on_hand": 5,
        "reserved": 2,
        "free": 3,
        "incoming": 6,
        "next_expected": "2026-11-20",
        "cells": [{"cell": "B-04-1", "on_hand": 5}],
        **extra,
    }


def reservation(**extra: Any) -> dict[str, Any]:
    return {
        "id": 41,
        "product_id": 3,
        "product_name": "Перевод стрелочный Р65 1/11",
        "deal": ref(),
        "quote_item_id": 7,
        "quantity": 2,
        "shipped_quantity": 0,
        "remaining": 2,
        "status": "active",
        "created_at": "2026-10-26T09:00:00+00:00",
        "created_by_name": "Демо Снабженцев",
        **extra,
    }


@pytest.fixture
def erp(be: Backends) -> respx.MockRouter:
    """ERP: заявка найдена в лёгком справочнике, заказ — отбором по номеру."""
    be.router.get(f"{CALC}/deals/").mock(return_value=httpx.Response(200, json=refs(deal())))
    be.router.get(f"{STOCK}/orders/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [order_row()],
                "rights": {"manage": True, "ship": True, "prices": True},
            },
        )
    )
    return be.router


def stock_calls(router: respx.MockRouter) -> list[Any]:
    return [
        c
        for c in router.calls
        if c.request.url.host == "erp.test" and "/api/v1/stock" in c.request.url.path
    ]


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method, f"/api/v1{path}", json=body, headers={"X-CSRF-Token": web.csrf}
    )


# --- доступ: 403 до ERP ------------------------------------------------------------------------

ACTIONS: list[tuple[str, str, Any]] = [
    ("POST", "/erp/stock/adjustments", {"product_id": "3", "quantity": 1}),
    ("DELETE", "/erp/stock/reservations/41", None),
    ("PUT", f"/erp/calc/{NUMBER}/lines/7/reserve", {"quantity": 1}),
    ("DELETE", f"/erp/calc/{NUMBER}/lines/7/reserve", None),
    ("POST", f"/erp/calc/{NUMBER}/price-requests", {"supplier_id": "5", "line_ids": ["7"]}),
    ("POST", "/erp/price-requests/3/answer", {}),
    (
        "POST",
        "/erp/stock/orders",
        {"supplier_id": "5", "lines": [{"product_id": "3", "quantity": 1}]},
    ),
    ("POST", "/erp/stock/orders/from-request", {"request": NUMBER, "supplier_id": "5"}),
    ("PATCH", f"/erp/stock/orders/{ORDER}", {"note": "x"}),
    ("POST", f"/erp/stock/orders/{ORDER}/send", {}),
    ("POST", f"/erp/stock/orders/{ORDER}/confirm", {}),
    ("POST", f"/erp/stock/orders/{ORDER}/cancel", {}),
    (
        "POST",
        f"/erp/stock/orders/{ORDER}/receipts",
        {"lines": [{"order_line_id": "77", "quantity": 1}]},
    ),
    (
        "POST",
        "/erp/stock/shipments",
        {"request": NUMBER, "lines": [{"reservation_id": "41", "quantity": 1}]},
    ),
    ("GET", "/erp/stock/overdue", None),
]
READS = [
    "/erp/stock/balances",
    "/erp/stock/balances/3",
    "/erp/stock/reservations",
    "/erp/stock/suppliers",
    "/erp/stock/orders",
    f"/erp/stock/orders/{ORDER}",
    "/erp/stock/receipts",
    "/erp/stock/shipments",
]


@pytest.mark.parametrize("role", ["ADMIN"])
async def test_without_the_stock_section_everything_is_403_and_erp_is_untouched(
    web: Web, erp: respx.MockRouter, role: str
) -> None:
    await web.login([role])
    for path in READS:
        assert (await web.client.get(f"/api/v1{path}")).status_code == 403, path
    for method, path, body in ACTIONS:
        assert (await call(web, method, path, body)).status_code == 403, (method, path)
    assert stock_calls(erp) == []


@pytest.mark.parametrize("role", ["MANAGER", "ACCOUNTANT"])
async def test_read_only_roles_read_the_warehouse_but_cannot_act(
    web: Web, erp: respx.MockRouter, role: str
) -> None:
    """`erp.stock: read` (менеджер, бухгалтер) — чтение; любое действие — 403 до ERP."""
    await web.login([role])
    erp.get(f"{STOCK}/balances/").mock(
        return_value=httpx.Response(
            200, json={"results": [stock_row()], "rights": {"manage": False, "ship": False}}
        )
    )
    assert (await web.client.get("/api/v1/erp/stock/balances")).status_code == 200
    before = len(stock_calls(erp))
    for method, path, body in ACTIONS:
        assert (await call(web, method, path, body)).status_code == 403, (method, path)
    assert len(stock_calls(erp)) == before, "ни одного вызова ERP по действию"


# --- чтение ------------------------------------------------------------------------------------


async def test_balances_and_product(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.get(f"{STOCK}/balances/").mock(
        return_value=httpx.Response(
            200, json={"results": [stock_row()], "rights": {"manage": True, "ship": True}}
        )
    )
    erp.get(f"{STOCK}/balances/3/").mock(
        return_value=httpx.Response(
            200,
            json={
                **stock_row(),
                "reservations": [reservation()],
                "incoming_orders": [
                    {
                        "order_id": 31,
                        "number": ORDER,
                        "status": "confirmed",
                        "supplier_name": "ООО Вымышленный Поставщик",
                        "expected_date": "2026-11-20",
                        "quantity_left": 6,
                    }
                ],
                "movements": [
                    {
                        "kind": "receipt",
                        "quantity": 4,
                        "cell": "B-02",
                        "at": "2026-10-25T09:00:00+00:00",
                        "by_name": "Демо",
                        "note": ORDER,
                    }
                ],
                "rights": {"manage": True, "ship": True},
            },
        )
    )

    listing = await web.client.get(
        "/api/v1/erp/stock/balances", params={"q": "стрелочный", "only": "reserved"}
    )
    assert listing.status_code == 200, listing.json()
    check(listing, "/erp/stock/balances", "get")
    (row,) = listing.json()["items"]
    assert (row["product_id"], row["on_hand"], row["reserved"], row["free"], row["incoming"]) == (
        "3",
        5,
        2,
        3,
        6,
    )
    assert dict(erp.calls.last.request.url.params) == {"q": "стрелочный", "only": "reserved"}

    detail = await web.client.get("/api/v1/erp/stock/balances/3")
    check(detail, "/erp/stock/balances/{product_id}", "get")
    body = detail.json()
    assert body["reservations"][0]["request"] == {
        "number": NUMBER,
        "client": "ООО Пример Логистик",
        "path": f"/erp/calc/{ENCODED}",
    }
    assert body["incoming_orders"][0]["path"] == f"/erp/stock/{ORDER_ENCODED}"
    assert body["movements"][0]["by"] == "Демо"


async def test_a_project_reservation_links_to_the_project_in_eds(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.get(f"{STOCK}/reservations/").mock(
        return_value=httpx.Response(
            200, json={"results": [reservation(deal=ref(number="ПР-2026-104"))]}
        )
    )
    response = await web.client.get("/api/v1/erp/stock/reservations")
    check(response, "/erp/stock/reservations", "get")
    assert response.json()["items"][0]["request"]["path"] == "/eds/projects/%D0%9F%D0%A0-2026-104"


async def test_reservations_of_a_request_are_found_by_its_number(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["SUPPLY"])
    route = erp.get(f"{STOCK}/reservations/").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    response = await web.client.get("/api/v1/erp/stock/reservations", params={"request": NUMBER})
    assert response.status_code == 200
    assert dict(route.calls.last.request.url.params) == {"deal_id": "104"}


# --- резерв строки: оркестрация ----------------------------------------------------------------


async def test_reserve_posts_to_stock_then_returns_the_fresh_sheet(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    reserve = erp.post(f"{STOCK}/reservations/").mock(
        return_value=httpx.Response(201, json=reservation())
    )
    fresh = sheet(
        lines=[line(stock={"on_hand": 5, "free": 3, "cell": "B-04-1", "reserved": 2}, kind="goods")]
    )
    fresh["rights"] = {**fresh["rights"], "stock": True}
    read = erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=fresh))

    response = await call(web, "PUT", f"/erp/calc/{ENCODED}/lines/7/reserve", {"quantity": 2})

    assert response.status_code == 200, response.json()
    check(response, "/erp/calc/{number}/lines/{line_id}/reserve", "put")
    assert json.loads(reserve.calls.last.request.content) == {
        "deal_id": 104,
        "quote_item_id": 7,
        "quantity": 2,
    }
    assert read.called
    goods = response.json()["lines"][0]
    assert goods["stock"] == {"on_hand": 5, "free": 3, "cell": "B-04-1", "reserved": 2}
    assert response.json()["rights"]["stock"] is True


async def test_release_finds_the_reservation_of_the_line_among_the_requests(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    listing = erp.get(f"{STOCK}/reservations/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    reservation(id=40, quote_item_id=6),
                    reservation(id=41, quote_item_id=7),
                ]
            },
        )
    )
    release = erp.delete(f"{STOCK}/reservations/41/").mock(
        return_value=httpx.Response(200, json=reservation(status="released"))
    )
    erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=sheet()))

    response = await call(web, "DELETE", f"/erp/calc/{ENCODED}/lines/7/reserve")

    assert response.status_code == 200, response.json()
    check(response, "/erp/calc/{number}/lines/{line_id}/reserve", "delete")
    assert dict(listing.calls.last.request.url.params) == {"deal_id": "104"}
    assert release.called
    missing = await call(web, "DELETE", f"/erp/calc/{ENCODED}/lines/99/reserve")
    assert missing.status_code == 404
    assert missing.json()["details"]["reason"] == "reservation_not_found"


async def test_reserve_refusals_are_translated(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = erp.post(f"{STOCK}/reservations/")
    route.mock(return_value=httpx.Response(409, json={"detail": "NOT_ENOUGH_STOCK", "free": 1}))
    response = await call(web, "PUT", f"/erp/calc/{ENCODED}/lines/7/reserve", {"quantity": 5})
    assert response.status_code == 409
    check(response, "/erp/calc/{number}/lines/{line_id}/reserve", "put")
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert body["source"] == "erp"
    assert body["details"]["reason"] == "not_enough_stock"
    assert body["details"]["free"] == 1

    route.mock(return_value=httpx.Response(400, json={"detail": "QUANTITY_OUT_OF_RANGE", "max": 2}))
    over = await call(web, "PUT", f"/erp/calc/{ENCODED}/lines/7/reserve", {"quantity": 5})
    assert over.status_code == 422
    assert over.json()["details"]["max"] == 2

    route.mock(return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"}))
    refused = await call(web, "PUT", f"/erp/calc/{ENCODED}/lines/7/reserve", {"quantity": 1})
    assert refused.status_code == 403
    assert refused.json()["details"]["reason"] == "role_not_permitted"

    route.mock(side_effect=httpx.ConnectError("down"))
    down = await call(web, "PUT", f"/erp/calc/{ENCODED}/lines/7/reserve", {"quantity": 1})
    assert down.status_code == 503


# --- запрос цены -------------------------------------------------------------------------------


def price_request(**extra: Any) -> dict[str, Any]:
    return {
        "id": 3,
        "supplier": {"id": 5, "name": "ООО Вымышленный Поставщик"},
        "deal_id": 104,
        "deal_number": NUMBER,
        "requested_at": "2026-10-28T09:00:00+00:00",
        "requested_by_name": "Демо Снабженцев",
        "to_email": "sales@vendor.example",
        "subject": f"Запрос цены и срока поставки — {NUMBER}",
        "note": "Нужны сертификаты",
        "status": "sent",
        "error": None,
        "answered_at": None,
        "answered_by_name": None,
        "answer_note": None,
        "lines": [
            {
                "quote_item_id": 7,
                "name": "Перевод стрелочный Р65 1/11",
                "article": "СП-Р65-11",
                "quantity": 2,
                "unit": "шт.",
            }
        ],
        **extra,
    }


async def test_price_request_goes_through_erp_and_is_listed(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    create = erp.post(f"{STOCK}/price-requests/").mock(
        return_value=httpx.Response(201, json=price_request())
    )
    journal = erp.get(f"{STOCK}/price-requests/").mock(
        return_value=httpx.Response(200, json={"results": [price_request()]})
    )

    created = await call(
        web,
        "POST",
        f"/erp/calc/{ENCODED}/price-requests",
        {"supplier_id": "5", "line_ids": ["7"], "note": "Нужны сертификаты"},
    )
    assert created.status_code == 200, created.json()
    check(created, "/erp/calc/{number}/price-requests", "post")
    assert json.loads(create.calls.last.request.content) == {
        "deal_id": 104,
        "supplier_id": 5,
        "line_ids": [7],
        "note": "Нужны сертификаты",
    }
    assert created.json()["lines"][0]["line_id"] == "7"
    assert created.json()["request"] == NUMBER

    listed = await web.client.get(f"/api/v1/erp/calc/{ENCODED}/price-requests")
    check(listed, "/erp/calc/{number}/price-requests", "get")
    assert dict(journal.calls.last.request.url.params) == {"deal_id": "104"}
    assert listed.json()["items"][0]["status"] == "sent"


async def test_price_request_refusals(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["SUPPLY"])
    route = erp.post(f"{STOCK}/price-requests/")
    route.mock(return_value=httpx.Response(409, json={"detail": "SUPPLIER_EMAIL_REQUIRED"}))
    no_mail = await call(
        web, "POST", f"/erp/calc/{ENCODED}/price-requests", {"supplier_id": "5", "line_ids": ["7"]}
    )
    assert no_mail.status_code == 409
    assert no_mail.json()["details"]["reason"] == "supplier_email_required"
    route.mock(return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"}))
    assert (
        await call(
            web,
            "POST",
            f"/erp/calc/{ENCODED}/price-requests",
            {"supplier_id": "5", "line_ids": ["7"]},
        )
    ).status_code == 403
    bad = await call(
        web, "POST", f"/erp/calc/{ENCODED}/price-requests", {"supplier_id": "5", "line_ids": ["x"]}
    )
    assert bad.status_code == 422
    nothing = await call(
        web, "POST", f"/erp/calc/{ENCODED}/price-requests", {"supplier_id": "5", "line_ids": []}
    )
    assert nothing.status_code == 422


async def test_answer_is_forwarded(web: Web, erp: respx.MockRouter, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    route = erp.post(f"{STOCK}/price-requests/3/answer/").mock(
        return_value=httpx.Response(
            200, json=price_request(answered_at="2026-10-28T10:00:00+00:00", answer_note="90 млн")
        )
    )
    response = await call(web, "POST", "/erp/price-requests/3/answer", {"note": "90 млн"})
    assert response.status_code == 200
    check(response, "/erp/price-requests/{request_id}/answer", "post")
    assert json.loads(route.calls.last.request.content) == {"note": "90 млн"}


# --- заказы поставщикам ------------------------------------------------------------------------


async def test_orders_list_and_card_found_by_number(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    listing = await web.client.get(
        "/api/v1/erp/stock/orders", params={"status": "confirmed", "overdue": "true"}
    )
    assert listing.status_code == 200, listing.json()
    check(listing, "/erp/stock/orders", "get")
    assert dict(erp.calls.last.request.url.params) == {"status": "confirmed", "overdue": "1"}
    (row,) = listing.json()["items"]
    assert row["number"] == ORDER
    assert row["path"] == f"/erp/stock/{ORDER_ENCODED}"
    assert row["requests"][0]["number"] == NUMBER
    assert row["total"] == "900000.00"

    erp.get(f"{STOCK}/orders/31/").mock(return_value=httpx.Response(200, json=order_detail()))
    card = await web.client.get(f"/api/v1/erp/stock/orders/{ORDER_ENCODED}")
    assert card.status_code == 200, card.json()
    check(card, "/erp/stock/orders/{order_number}", "get")
    body = card.json()
    assert body["lines"][0]["id"] == "77"
    assert body["lines"][0]["line_id"] == "7"
    assert body["receipts"][0]["lines"][0]["cell"] == "B-02"
    # заказ нашли отбором по номеру, id из номера не разбирался
    assert any(c.request.url.params.get("number") == ORDER for c in stock_calls(erp))


async def test_unknown_order_number_is_404(web: Web, be: Backends) -> None:
    await web.login(["SUPPLY"])
    be.router.get(f"{STOCK}/orders/").mock(return_value=httpx.Response(200, json={"results": []}))
    response = await web.client.get(f"/api/v1/erp/stock/orders/{ORDER_ENCODED}")
    assert response.status_code == 404
    assert response.json()["details"]["reason"] == "order_not_found"


@pytest.mark.parametrize(
    ("role", "visible"),
    [
        ("SUPPLY", True),
        ("DIRECTOR", True),
        ("ENGINEER", False),
        ("MANAGER", False),
        ("ACCOUNTANT", False),
    ],
)
async def test_supplier_prices_are_cut_for_roles_without_them(
    web: Web, erp: respx.MockRouter, check: ContractChecker, role: str, visible: bool
) -> None:
    """Цены поставщиков в заказе — `supplier_prices`, `cost_margin` или зона товаров. ERP режет
    сам; BFF режет ещё раз, даже если ERP по ошибке отдал цену (защита в глубину)."""
    await web.login([role])
    erp.get(f"{STOCK}/orders/31/").mock(return_value=httpx.Response(200, json=order_detail()))

    card = await web.client.get(f"/api/v1/erp/stock/orders/{ORDER_ENCODED}")
    listing = await web.client.get("/api/v1/erp/stock/orders")

    check(card, "/erp/stock/orders/{order_number}", "get")
    body = card.json()
    assert (body["total"] is not None) == visible
    assert (body["lines"][0]["unit_price"] is not None) == visible
    assert (body["lines"][0]["line_total"] is not None) == visible
    assert body["rights"]["prices"] is (visible and True)
    assert (listing.json()["items"][0]["total"] is not None) == visible
    if not visible:
        assert "900000" not in card.text
        assert "90000.00" not in card.text


async def test_create_order_resolves_the_request_number_and_cuts_nothing_else(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    create = erp.post(f"{STOCK}/orders/").mock(
        return_value=httpx.Response(201, json=order_detail(status="draft", number=ORDER))
    )
    response = await call(
        web,
        "POST",
        "/erp/stock/orders",
        {
            "supplier_id": "5",
            "expected_date": "2026-11-20",
            "lines": [
                {
                    "product_id": "3",
                    "quantity": 10,
                    "unit_price": "90000.00",
                    "request": NUMBER,
                    "line_id": "7",
                },
                {"product_id": "4", "quantity": 1},
            ],
        },
    )
    assert response.status_code == 201, response.json()
    check(response, "/erp/stock/orders", "post")
    sent = json.loads(create.calls.last.request.content)
    assert sent["supplier_id"] == 5
    assert sent["expected_date"] == "2026-11-20"
    assert sent["lines"][0] == {
        "product_id": 3,
        "quantity": 10,
        "unit_price": "90000.00",
        "deal_id": 104,
        "quote_item_id": 7,
    }
    assert sent["lines"][1] == {"product_id": 4, "quantity": 1}

    lonely = await call(
        web,
        "POST",
        "/erp/stock/orders",
        {"supplier_id": "5", "lines": [{"product_id": "3", "quantity": 1, "line_id": "7"}]},
    )
    assert lonely.status_code == 422
    assert lonely.json()["details"]["reason"] == "request_and_line_together"
    empty = await call(web, "POST", "/erp/stock/orders", {"supplier_id": "5", "lines": []})
    assert empty.status_code == 422


async def test_price_in_a_line_without_the_right_is_refused_by_erp_and_reported_on_the_field(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["ENGINEER"])
    erp.post(f"{STOCK}/orders/").mock(
        return_value=httpx.Response(403, json={"detail": "PRICES_FORBIDDEN"})
    )
    response = await call(
        web,
        "POST",
        "/erp/stock/orders",
        {"supplier_id": "5", "lines": [{"product_id": "3", "quantity": 1, "unit_price": "1.00"}]},
    )
    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "prices_forbidden"
    assert response.json()["details"]["fields"] == ["unit_price"]


async def test_order_from_request_resolves_the_number(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = erp.post(f"{STOCK}/orders/from-deal/").mock(
        return_value=httpx.Response(201, json=order_detail(status="draft"))
    )
    response = await call(
        web, "POST", "/erp/stock/orders/from-request", {"request": NUMBER, "supplier_id": "5"}
    )
    assert response.status_code == 201
    check(response, "/erp/stock/orders/from-request", "post")
    assert json.loads(route.calls.last.request.content) == {"deal_id": 104, "supplier_id": 5}
    erp.post(f"{STOCK}/orders/from-deal/").mock(
        return_value=httpx.Response(409, json={"detail": "NO_SHORTAGE"})
    )
    again = await call(
        web, "POST", "/erp/stock/orders/from-request", {"request": NUMBER, "supplier_id": "5"}
    )
    assert again.status_code == 409
    assert again.json()["details"]["reason"] == "no_shortage"


async def test_transitions_are_posted_to_erp_by_order_id(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    routes = {
        action: erp.post(f"{STOCK}/orders/31/{action}/").mock(
            return_value=httpx.Response(200, json=order_detail())
        )
        for action in ("send", "confirm", "cancel", "receipts")
    }
    expected = {
        "send": ({"to_email": "orders@vendor.example"}, {"to_email": "orders@vendor.example"}),
        "confirm": ({"expected_date": "2026-11-25"}, {"expected_date": "2026-11-25"}),
        "cancel": ({"reason": "Передумали"}, {"reason": "Передумали"}),
        "receipts": (
            {
                "lines": [{"order_line_id": "77", "quantity": 4, "cell": "B-02"}],
                "supplier_doc": "НП-77",
            },
            {
                "lines": [{"order_line_id": 77, "quantity": 4, "cell": "B-02"}],
                "supplier_doc": "НП-77",
            },
        ),
    }
    for action, (body, sent) in expected.items():
        response = await call(web, "POST", f"/erp/stock/orders/{ORDER_ENCODED}/{action}", body)
        assert response.status_code == 200, (action, response.json())
        check(response, f"/erp/stock/orders/{{order_number}}/{action}", "post")
        assert json.loads(routes[action].calls.last.request.content) == sent, action
    # без тела — пустое действие
    assert (await call(web, "POST", f"/erp/stock/orders/{ORDER_ENCODED}/send")).status_code == 200
    assert json.loads(routes["send"].calls.last.request.content) == {"to_email": ""}


async def test_transition_refusals_keep_the_reason(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    send = erp.post(f"{STOCK}/orders/31/send/")
    for status, detail, reason in (
        (409, "TRANSITION_NOT_ALLOWED", "transition_not_allowed"),
        (409, "SUPPLIER_EMAIL_REQUIRED", "supplier_email_required"),
        (409, "EMAIL_FAILED", "email_failed"),
    ):
        send.mock(return_value=httpx.Response(status, json={"detail": detail}))
        response = await call(web, "POST", f"/erp/stock/orders/{ORDER_ENCODED}/send", {})
        assert response.status_code == 409, detail
        check(response, "/erp/stock/orders/{order_number}/send", "post")
        assert response.json()["details"]["reason"] == reason
    erp.post(f"{STOCK}/orders/31/receipts/").mock(
        return_value=httpx.Response(400, json={"detail": "QUANTITY_OUT_OF_RANGE", "max": 2})
    )
    over = await call(
        web,
        "POST",
        f"/erp/stock/orders/{ORDER_ENCODED}/receipts",
        {"lines": [{"order_line_id": "77", "quantity": 9}]},
    )
    assert over.status_code == 422
    assert over.json()["details"]["max"] == 2
    erp.post(f"{STOCK}/orders/31/receipts/").mock(
        return_value=httpx.Response(404, json={"detail": "LINE_NOT_FOUND"})
    )
    foreign = await call(
        web,
        "POST",
        f"/erp/stock/orders/{ORDER_ENCODED}/receipts",
        {"lines": [{"order_line_id": "5", "quantity": 1}]},
    )
    assert foreign.status_code == 404
    assert foreign.json()["details"]["reason"] == "line_not_found"


async def test_patch_needs_something_and_sends_only_what_changed(
    web: Web, erp: respx.MockRouter
) -> None:
    await web.login(["SUPPLY"])
    route = erp.patch(f"{STOCK}/orders/31/").mock(
        return_value=httpx.Response(200, json=order_detail())
    )
    nothing = await call(web, "PATCH", f"/erp/stock/orders/{ORDER_ENCODED}", {})
    assert nothing.status_code == 422
    ok = await call(
        web,
        "PATCH",
        f"/erp/stock/orders/{ORDER_ENCODED}",
        {"expected_date": "2026-12-01", "note": "Перенос"},
    )
    assert ok.status_code == 200
    assert json.loads(route.calls.last.request.content) == {
        "expected_date": "2026-12-01",
        "note": "Перенос",
    }
    clear = await call(web, "PATCH", f"/erp/stock/orders/{ORDER_ENCODED}", {"expected_date": None})
    assert clear.status_code == 200
    assert json.loads(route.calls.last.request.content) == {"expected_date": None}


# --- приёмка, отгрузки, поставщики -------------------------------------------------------------


async def test_receipts_suppliers_and_shipments(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.get(f"{STOCK}/receipts/").mock(
        return_value=httpx.Response(
            200,
            json={
                "pending": [
                    {
                        "order_id": 31,
                        "order_number": ORDER,
                        "supplier_name": "ООО Вымышленный Поставщик",
                        "expected_date": "2026-11-20",
                        "overdue": False,
                        "order_line_id": 77,
                        "name": "Перевод стрелочный Р65 1/11",
                        "article": "СП-Р65-11",
                        "unit": "шт.",
                        "quantity": 10,
                        "received_quantity": 4,
                        "deal": ref(),
                    }
                ],
                "done": [
                    {
                        "id": 9,
                        "order_id": 31,
                        "order_number": ORDER,
                        "supplier_name": "ООО Вымышленный Поставщик",
                        "received_at": "2026-10-25T09:00:00+00:00",
                        "received_by_name": "Демо",
                        "supplier_doc": "НП-77",
                        "quantity": 4,
                        "lines": [{"name": "Перевод", "quantity": 4, "cell": "B-02"}],
                    }
                ],
                "rights": {"manage": True, "ship": True},
            },
        )
    )
    receipts = await web.client.get("/api/v1/erp/stock/receipts")
    check(receipts, "/erp/stock/receipts", "get")
    assert receipts.json()["pending"][0]["order_line_id"] == "77"
    assert receipts.json()["done"][0]["order_path"] == f"/erp/stock/{ORDER_ENCODED}"

    erp.get(f"{STOCK}/suppliers/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 5,
                        "name": "ООО Вымышленный Поставщик",
                        "inn": "7700000302",
                        "email": "sales@vendor.example",
                    }
                ]
            },
        )
    )
    suppliers = await web.client.get("/api/v1/erp/stock/suppliers", params={"q": "Вымыш"})
    check(suppliers, "/erp/stock/suppliers", "get")
    assert suppliers.json()["items"][0] == {
        "id": "5",
        "name": "ООО Вымышленный Поставщик",
        "inn": "7700000302",
        "email": "sales@vendor.example",
    }

    shipment = {
        "id": 12,
        "number": "ОТГ-2026-014",
        "deal": ref(number="ПР-2026-104"),
        "tracking": "TRK-1",
        "carrier": "ООО Перевозка",
        "note": None,
        "shipped_at": "2026-10-28T09:00:00+00:00",
        "shipped_by_name": "Демо",
        "lines": [{"product_id": 3, "name": "Перевод", "quantity": 2, "cell": "B-04-1"}],
    }
    listing = erp.get(f"{STOCK}/shipments/").mock(
        return_value=httpx.Response(
            200, json={"results": [shipment], "rights": {"manage": True, "ship": True}}
        )
    )
    shipments = await web.client.get("/api/v1/erp/stock/shipments", params={"request": NUMBER})
    check(shipments, "/erp/stock/shipments", "get")
    assert dict(listing.calls.last.request.url.params) == {"deal_id": "104"}
    assert shipments.json()["items"][0]["request"]["path"] == "/eds/projects/%D0%9F%D0%A0-2026-104"

    create = erp.post(f"{STOCK}/shipments/").mock(return_value=httpx.Response(201, json=shipment))
    created = await call(
        web,
        "POST",
        "/erp/stock/shipments",
        {
            "request": NUMBER,
            "lines": [{"reservation_id": "41", "quantity": 2}],
            "tracking": "TRK-1",
            "carrier": "ООО Перевозка",
        },
    )
    assert created.status_code == 201, created.json()
    check(created, "/erp/stock/shipments", "post")
    assert json.loads(create.calls.last.request.content) == {
        "deal_id": 104,
        "lines": [{"reservation_id": 41, "quantity": 2}],
        "tracking": "TRK-1",
        "carrier": "ООО Перевозка",
    }
    create.mock(return_value=httpx.Response(409, json={"detail": "FULFILLMENT_NOT_READY"}))
    early = await call(
        web,
        "POST",
        "/erp/stock/shipments",
        {"request": NUMBER, "lines": [{"reservation_id": "41", "quantity": 1}]},
    )
    assert early.status_code == 409
    assert early.json()["details"]["reason"] == "fulfillment_not_ready"


async def test_unknown_request_number_is_404_before_any_stock_call(web: Web, be: Backends) -> None:
    await web.login(["SUPPLY"])
    be.router.get(f"{CALC}/deals/").mock(return_value=httpx.Response(200, json={"results": []}))
    response = await web.client.get(
        "/api/v1/erp/stock/shipments", params={"request": "ЗВ-2026-999"}
    )
    assert response.status_code == 404
    assert response.json()["details"]["reason"] == "calc_task_not_found"


# --- «Мои задачи»: вид supplier_overdue --------------------------------------------------------


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def overdue_row(**extra: Any) -> dict[str, Any]:
    return {
        "id": 31,
        "number": ORDER,
        "status": "confirmed",
        "supplier_name": "ООО Вымышленный Поставщик",
        "expected_date": "2027-01-10",
        "days_overdue": 5,
        **extra,
    }


async def test_overdue_order_is_a_queue_row_that_opens_the_order(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["overdue"] = {
        "results": [overdue_row(), overdue_row(id=32, number="ЗП-2026-032", days_overdue=1)]
    }
    await web.login(["SUPPLY"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200, response.json()
    check(response, "/queue", "get")
    items = [i for i in response.json()["items"] if i["kind"] == "supplier_overdue"]
    assert [i["object"]["number"] for i in items] == [ORDER, "ЗП-2026-032"]
    first = items[0]
    assert first["title"] == f"Просрочен заказ {ORDER}"
    assert "5 дн. просрочки" in first["subtitle"]
    assert "ООО Вымышленный Поставщик" in first["subtitle"]
    assert first["due_label"] == "overdue"
    assert first["object"] == {
        "kind": "supplier_order",
        "number": ORDER,
        "title": "ООО Вымышленный Поставщик",
        "path": f"/erp/stock/{ORDER_ENCODED}",
    }
    assert response.json()["sources"]["erp"] == "ok"


@pytest.mark.parametrize("role", ["SUPPLY", "ENGINEER", "DIRECTOR"])
async def test_the_row_goes_to_roles_with_the_stock_section_in_full(
    web: Web, fb: FeedBackends, role: str
) -> None:
    fb.state["overdue"] = {"results": [overdue_row()]}
    await web.login([role])
    kinds = [i["kind"] for i in (await web.client.get("/api/v1/queue")).json()["items"]]
    assert kinds.count("supplier_overdue") == 1


@pytest.mark.parametrize("role", ["MANAGER", "ACCOUNTANT"])
async def test_read_only_roles_get_no_row_and_erp_is_not_asked(
    web: Web, fb: FeedBackends, role: str
) -> None:
    fb.state["overdue"] = {"results": [overdue_row()]}
    await web.login([role])
    response = await web.client.get("/api/v1/queue")
    assert "supplier_overdue" not in [i["kind"] for i in response.json()["items"]]
    assert fb.calls(fb.erp["overdue"]) == 0


async def test_when_erp_fails_the_queue_is_partial_not_an_error(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    """Источники не зависят друг от друга: ERP не ответил — 200, `sources.erp = unavailable`,
    строки CRM на месте."""
    from tests.feeds_support import escalation, lead

    fb.state["inbox"] = {
        "escalations": [
            lead(2041, "Демо Клиентов", escalation=escalation(), last_msg=fb.m.ago(minutes=5))
        ],
        "mine": [],
        "unassigned": [],
    }
    fb.state["overdue"] = {"results": [overdue_row()]}
    fb.erp_down = httpx.ConnectError("erp down")
    await web.login(
        [
            {
                "id": 91,
                "name": "Снабженец-лидов",
                "system": False,
                "code": None,
                "access": {"erp.stock": "full", "crm.leads": "full", "dashboard.queue": "full"},
                "restricted_fields": [],
            }
        ]
    )

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200, response.json()
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"]["erp"] == "unavailable"
    assert body["sources"]["crm"] == "ok"
    assert [i["kind"] for i in body["items"]] == ["take_lead"], (
        "строки CRM остались, просроченных заказов нет"
    )

    cards = await web.client.get("/api/v1/queue/cards")
    check(cards, "/queue/cards", "get")
    counters = await web.client.get("/api/v1/menu-counters")
    check(counters, "/menu-counters", "get")
    assert counters.json()["sources"]["erp"] == "unavailable"


async def test_counter_counts_the_overdue_orders(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["overdue"] = {"results": [overdue_row(), overdue_row(id=32, number="ЗП-2026-032")]}
    await web.login(["SUPPLY"])

    counters = await web.client.get("/api/v1/menu-counters")
    check(counters, "/menu-counters", "get")
    stock = next(
        i for i in counters.json()["items"] if (i["module"], i["section"]) == ("erp", "stock")
    )
    assert stock == {"module": "erp", "section": "stock", "count": 2, "attention": True}


async def test_the_overdue_notification_opens_the_order(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    note = notification(5, "supplier_order.overdue", f"Заказ {ORDER} просрочен")
    note["event_params"] = {"number": ORDER, "supplier": "ООО Вымышленный Поставщик", "days": 3}
    fb.state["notifications"] = {"count": 1, "next": None, "previous": None, "results": [note]}
    await web.login(["SUPPLY"])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200, response.json()
    check(response, "/notifications", "get")
    (item,) = response.json()["items"]
    assert item["tab"] == "decisions"
    assert item["object"] == {
        "kind": "supplier_order",
        "number": ORDER,
        "title": "ООО Вымышленный Поставщик",
        "path": f"/erp/stock/{ORDER_ENCODED}",
    }
