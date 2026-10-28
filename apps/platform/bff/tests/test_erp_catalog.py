"""Расчёт · Номенклатура и поставщики, бригады, справочники и Техдокументация (контракт BFF 0.26.0,
тег `erp-catalog`; D2-3).

ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Решения о правах на операции —
за ERP; здесь проверяются: раздел `erp.stock` (без него и при уровне `read` изменений BFF в ERP не
отправляет), перевод ответов и отказов ERP, и вырезание закрытых полей по каталогу ролей — цена
закупки без `supplier_prices`, ставка бригады без `cost_margin` и без `erp.calc.services` — даже
если ERP их прислала (администратор ERP видит всё)."""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.roles import custom

API = f"{ERP_URL}/api/v1"

OFFER = {
    "id": 31,
    "supplier": {"id": 9, "name": "ООО Поставщик Север"},
    "product": {"id": 4, "name": "Кабель силовой ВВГнг 3×2,5", "sku": "RT-0001"},
    "supplier_sku": "N-77",
    "price": {"amount": "12.50", "currency": "USD"},
    "quota_qty": 500,
    "min_order_qty": 10,
    "in_stock_lead_days": 2,
    "order_lead_days": 14,
    "stock_status": "IN_STOCK",
    "valid_from": None,
    "valid_until": "2026-12-31",
    "is_active": True,
    "validity": "ok",
}
ITEM = {
    "id": 4,
    "sku": "RT-0001",
    "name": "Кабель силовой ВВГнг 3×2,5",
    "kind": "stock",
    "is_service": False,
    "unit": {"id": 1, "code": "pcs", "name": "шт"},
    "vat_rate": None,
    "vat_effective": "12.00",
    "category": {"id": 2, "name": "Электрооборудование"},
    "status": "PUBLISHED",
    "offers_count": 1,
    "nearest_valid_until": "2026-12-31",
    "docs_count": 1,
}
ITEM_DETAIL = {
    **ITEM,
    "description": "Кабель",
    "gost_drawing": "ГОСТ 31996",
    "hs_code": "8544",
    "manufacturer_part_number": "",
    "brand": None,
    "offers": [OFFER],
    "prices_visible": True,
    "tech_docs": [{"id": 5, "title": "Паспорт кабеля", "kind": "certificate"}],
}
SUPPLIER = {
    "id": 9,
    "name": "ООО Поставщик Север",
    "tin": "300000777",
    "country": "Узбекистан",
    "offers_count": 3,
    "expired_count": 1,
    "expiring_count": 1,
    "nearest_valid_until": "2026-11-02",
}
BRIGADE = {
    "id": 3,
    "name": "Бригада монтажа №1",
    "kind": "brigade",
    "specialization": "Монтаж",
    "headcount": 4,
    "rate": {"amount": "800000.00", "currency": "UZS", "unit": "day"},
    "rate_visible": True,
    "note": "",
    "is_active": True,
}


def page(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(rows), "next": None, "previous": None, "results": rows}


def mock(be: Any) -> respx.MockRouter:
    return be.router


def body_of(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


READS = (
    ("GET", "/erp/catalog/lookups"),
    ("GET", "/erp/catalog/items"),
    ("GET", "/erp/catalog/items/4"),
    ("GET", "/erp/catalog/suppliers"),
    ("GET", "/erp/catalog/suppliers/9"),
    ("GET", "/erp/catalog/brigades"),
    ("GET", "/erp/catalog/category-requests"),
    ("GET", "/erp/catalog/exchange-rates"),
    ("GET", "/erp/catalog/hs-codes"),
    ("GET", "/erp/catalog/manufacturers"),
    ("GET", "/erp/docs/files"),
    ("GET", "/erp/docs/files/5/content"),
    ("GET", "/erp/docs/deals"),
)
WRITES = (
    ("POST", "/erp/catalog/items"),
    ("PATCH", "/erp/catalog/items/4"),
    ("PATCH", "/erp/catalog/suppliers/9/offers/31"),
    ("POST", "/erp/catalog/brigades"),
    ("PATCH", "/erp/catalog/brigades/3"),
    ("POST", "/erp/catalog/category-requests"),
    ("POST", "/erp/catalog/hs-codes"),
    ("PATCH", "/erp/catalog/hs-codes/8"),
    ("POST", "/erp/catalog/manufacturers"),
    ("PATCH", "/erp/catalog/manufacturers/2"),
    ("POST", "/erp/docs/files"),
    ("DELETE", "/erp/docs/files/5"),
)


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method,
        f"/api/v1{path}",
        json=body if body is not None else ({} if method not in ("GET", "DELETE") else None),
        headers={"X-CSRF-Token": web.csrf},
    )


def erp_data_calls(router: respx.MockRouter) -> list[Any]:
    return [
        c
        for c in router.calls
        if c.request.url.host == "erp.test" and "/auth/" not in c.request.url.path
    ]


# --- доступ: раздел erp.stock -----------------------------------------------------------------


async def test_administrator_has_no_erp_stock_and_never_reaches_erp(web: Web, be: Any) -> None:
    await web.login(["ADMIN"])
    for method, path in (*READS, *WRITES):
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"]["resource"] == "erp.stock", (method, path)
    assert erp_data_calls(be.router) == []


@pytest.mark.parametrize("role", ["MANAGER", "ACCOUNTANT"])
async def test_read_level_cannot_change_and_erp_is_not_called_for_writes(
    web: Web, be: Any, role: str
) -> None:
    """У менеджера и бухгалтера `erp.stock` только на чтение: изменения отсекает BFF."""
    await web.login([role])
    for method, path in WRITES:
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"] == {"resource": "erp.stock", "need": "full"}, (
            method,
            path,
        )
    assert erp_data_calls(be.router) == []


async def test_write_without_csrf_is_rejected(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await web.client.post(
        "/api/v1/erp/catalog/items", json={"name": "Х", "kind": "stock"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


# --- позиции ----------------------------------------------------------------------------------


async def test_items_list_forwards_filters_and_builds_the_page(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    route = (
        mock(be)
        .get(f"{API}/catalog/items/")
        .mock(return_value=httpx.Response(200, json={**page([ITEM]), "count": 41}))
    )

    response = await web.client.get(
        "/api/v1/erp/catalog/items",
        params={"q": "кабель", "kind": "stock", "category_id": "2", "page": 2, "page_size": 10},
    )

    assert response.status_code == 200
    check(response, "/erp/catalog/items", "get")
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (41, 2, 10)
    assert body["items"][0]["kind"] == "stock"
    assert body["items"][0]["unit"]["code"] == "pcs"
    assert body["items"][0]["category"] == {"id": "2", "name": "Электрооборудование"}
    sent = dict(route.calls.last.request.url.params)
    assert sent == {"q": "кабель", "kind": "stock", "category": "2", "page": "2", "page_size": "10"}
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


async def test_items_list_rejects_unknown_kind_before_erp(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await web.client.get("/api/v1/erp/catalog/items", params={"kind": "ghost"})
    assert response.status_code == 422
    assert erp_data_calls(be.router) == []


@pytest.mark.parametrize(
    ("role", "sees_price"),
    [
        ("SUPPLY", True),
        ("DIRECTOR", True),
        ("ENGINEER", False),
        ("MANAGER", False),
        ("ACCOUNTANT", True),
    ],
)
async def test_item_card_supplier_price_follows_the_role_even_if_erp_sent_it(
    web: Web, be: Any, check: ContractChecker, role: str, sees_price: bool
) -> None:
    """Каталог ролей решает, кто видит цены; ERP присылает цену всегда (как администратору)."""
    await web.login([role])
    mock(be).get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=ITEM_DETAIL))

    response = await web.client.get("/api/v1/erp/catalog/items/4")

    assert response.status_code == 200
    check(response, "/erp/catalog/items/{id}", "get")
    body = response.json()
    assert body["prices_visible"] is sees_price
    if sees_price:
        assert body["offers"][0]["price"] == {"amount": "12.50", "currency": "USD"}
    else:
        assert body["offers"][0]["price"] is None
        assert "12.50" not in response.text
    assert body["offers"][0]["quota_qty"] == 500
    assert body["offers"][0]["validity"] == "ok"
    assert body["tech_docs"] == [{"id": "5", "title": "Паспорт кабеля", "kind": "certificate"}]


async def test_item_card_hides_price_when_erp_itself_withholds_it(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    cut = {**ITEM_DETAIL, "prices_visible": False, "offers": [{**OFFER, "price": None}]}
    mock(be).get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=cut))

    body = (await web.client.get("/api/v1/erp/catalog/items/4")).json()

    assert body["prices_visible"] is False
    assert body["offers"][0]["price"] is None


async def test_item_create_and_update_translate_ids_and_report_erp_refusals(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    router = mock(be)
    post = router.post(f"{API}/catalog/items/").mock(
        return_value=httpx.Response(201, json={**ITEM_DETAIL, "offers": []})
    )
    patch = router.patch(f"{API}/catalog/items/4/").mock(
        return_value=httpx.Response(200, json={**ITEM_DETAIL, "offers": []})
    )

    created = await call(
        web,
        "POST",
        "/erp/catalog/items",
        {
            "name": "Реле",
            "kind": "service_time",
            "unit_id": "1",
            "category_id": "2",
            "vat_rate": "12.00",
        },
    )
    assert created.status_code == 201
    check(created, "/erp/catalog/items", "post")
    assert body_of(post) == {
        "name": "Реле",
        "kind": "service_time",
        "unit_id": 1,
        "category_id": 2,
        "vat_rate": "12.00",
    }

    cleared = await call(web, "PATCH", "/erp/catalog/items/4", {"vat_rate": None, "unit_id": None})
    assert cleared.status_code == 200
    check(cleared, "/erp/catalog/items/{id}", "patch")
    assert body_of(patch) == {"vat_rate": None, "unit_id": None}

    router.patch(f"{API}/catalog/items/4/").mock(
        return_value=httpx.Response(400, json={"detail": "VAT_RATE_INVALID"})
    )
    refused = await call(web, "PATCH", "/erp/catalog/items/4", {"vat_rate": "999"})
    assert refused.status_code == 422
    assert refused.json()["details"]["fields"] == ["vat_rate"]
    assert refused.json()["details"]["reason"] == "vat_rate_invalid"

    empty = await call(web, "PATCH", "/erp/catalog/items/4", {})
    assert empty.status_code == 422


async def test_erp_role_refusal_is_forbidden_from_erp_not_a_server_error(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/items/").mock(
        return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"})
    )
    response = await call(web, "POST", "/erp/catalog/items", {"name": "Х", "kind": "stock"})
    assert response.status_code == 403
    assert response.json()["source"] == "erp"
    assert response.json()["details"]["backend_code"] == "ROLE_NOT_PERMITTED"


# --- поставщики -------------------------------------------------------------------------------


async def test_suppliers_list_and_card_cut_prices_for_roles_without_the_field(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    router = mock(be)
    router.get(f"{API}/catalog/suppliers/").mock(
        return_value=httpx.Response(200, json=page([SUPPLIER]))
    )
    router.get(f"{API}/catalog/suppliers/9/").mock(
        return_value=httpx.Response(
            200,
            json={
                **SUPPLIER,
                "contact_person": "Менеджер",
                "phone": "+998 00 000 00 00",
                "email": "s@example.test",
                "website": "",
                "legal_address": "Ташкент",
                "offers": [OFFER],
                "prices_visible": True,
            },
        )
    )

    listed = await web.client.get("/api/v1/erp/catalog/suppliers", params={"q": "север"})
    assert listed.status_code == 200
    check(listed, "/erp/catalog/suppliers", "get")
    assert listed.json()["items"][0]["expiring_count"] == 1

    card = await web.client.get("/api/v1/erp/catalog/suppliers/9")
    assert card.status_code == 200
    check(card, "/erp/catalog/suppliers/{id}", "get")
    assert card.json()["prices_visible"] is False
    assert card.json()["offers"][0]["price"] is None
    assert "12.50" not in card.text
    assert card.json()["offers"][0]["valid_until"] == "2026-12-31"


async def test_offer_update_forwards_terms_and_keeps_the_price_cut(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    route = (
        mock(be)
        .patch(f"{API}/catalog/suppliers/9/offers/31/")
        .mock(return_value=httpx.Response(200, json=OFFER))
    )

    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/offers/31",
        {"quota_qty": 250, "valid_until": "2027-01-31", "stock_status": None},
    )

    assert response.status_code == 200
    check(response, "/erp/catalog/suppliers/{id}/offers/{offer_id}", "patch")
    assert response.json()["price"] is None  # у гл. инженера нет supplier_prices
    assert body_of(route) == {"quota_qty": 250, "valid_until": "2027-01-31", "stock_status": None}


async def test_offer_price_without_the_right_is_refused_before_erp(web: Web, be: Any) -> None:
    await web.login(["ENGINEER"])  # у гл. инженера нет supplier_prices
    route = (
        mock(be)
        .patch(f"{API}/catalog/suppliers/9/offers/31/")
        .mock(return_value=httpx.Response(200, json=OFFER))
    )
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/offers/31",
        {"price": {"amount": "1.00", "currency": "USD"}},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["details"]["restricted"] == "supplier_prices"
    assert not route.called


async def test_offer_price_with_the_right_goes_to_erp(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .patch(f"{API}/catalog/suppliers/9/offers/31/")
        .mock(return_value=httpx.Response(200, json=OFFER))
    )
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/offers/31",
        {"price": {"amount": "1.00", "currency": "USD"}},
    )
    assert response.status_code == 200
    assert route.called
    assert response.json()["price"] == {"amount": "12.50", "currency": "USD"}


async def test_offer_price_refusal_by_erp_is_still_forwarded_as_forbidden(
    web: Web, be: Any
) -> None:
    await web.login(["SUPPLY"])
    mock(be).patch(f"{API}/catalog/suppliers/9/offers/31/").mock(
        return_value=httpx.Response(403, json={"detail": "SUPPLIER_PRICES_REQUIRED"})
    )
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/offers/31",
        {"price": {"amount": "1.00", "currency": "USD"}},
    )
    assert response.status_code == 403
    assert response.json()["details"]["backend_code"] == "SUPPLIER_PRICES_REQUIRED"


# --- бригады ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "sees_rate"),
    [
        (["SUPPLY"], True),  # cost_margin
        (["DIRECTOR"], True),
        (["ENGINEER"], True),  # erp.calc.services
        (["MANAGER"], False),
        (["ACCOUNTANT"], False),
        ([custom(70, "Каталог без полей", {"erp.stock": "full"})], False),
    ],
)
async def test_brigade_rate_is_for_cost_margin_or_services_zone_only(
    web: Web, be: Any, check: ContractChecker, roles: list[Any], sees_rate: bool
) -> None:
    await web.login(roles)
    mock(be).get(f"{API}/catalog/brigades/").mock(
        return_value=httpx.Response(200, json=page([BRIGADE]))
    )

    response = await web.client.get("/api/v1/erp/catalog/brigades", params={"kind": "brigade"})

    assert response.status_code == 200
    check(response, "/erp/catalog/brigades", "get")
    row = response.json()["items"][0]
    assert row["rate_visible"] is sees_rate
    assert (row["rate"] is not None) is sees_rate
    if not sees_rate:
        assert "800000" not in response.text
    assert row["headcount"] == 4


async def test_brigade_create_and_update_pass_rate_and_deactivate(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    router = mock(be)
    post = router.post(f"{API}/catalog/brigades/").mock(
        return_value=httpx.Response(201, json=BRIGADE)
    )
    patch = router.patch(f"{API}/catalog/brigades/3/").mock(
        return_value=httpx.Response(200, json={**BRIGADE, "is_active": False})
    )

    created = await call(
        web,
        "POST",
        "/erp/catalog/brigades",
        {"name": "Бригада", "headcount": 4, "rate": {"amount": "800000", "currency": "UZS"}},
    )
    assert created.status_code == 201
    check(created, "/erp/catalog/brigades", "post")
    assert body_of(post)["rate"] == {"amount": "800000", "currency": "UZS"}

    off = await call(web, "PATCH", "/erp/catalog/brigades/3", {"is_active": False, "rate": None})
    assert off.status_code == 200
    assert off.json()["is_active"] is False
    check(off, "/erp/catalog/brigades/{id}", "patch")
    assert body_of(patch) == {"is_active": False, "rate": None}

    router.post(f"{API}/catalog/brigades/").mock(
        return_value=httpx.Response(403, json={"detail": "CREW_RATES_REQUIRED"})
    )
    refused = await call(
        web,
        "POST",
        "/erp/catalog/brigades",
        {"name": "Б", "rate": {"amount": "1", "currency": "UZS"}},
    )
    assert refused.status_code == 403


# --- запросы на категории ---------------------------------------------------------------------

REQUEST = {
    "id": 12,
    "company": 1,
    "company_name": "Своя компания",
    "requested_by_email": "supply@example.test",
    "proposed_name": "Кабельные лотки",
    "parent": None,
    "parent_name": "",
    "domain_type": None,
    "domain_type_code": "",
    "justification": "Не нашёл подходящей",
    "status": "PENDING",
    "resulting_category": None,
    "resulting_category_name": "",
    "review_notes": "",
    "reviewed_at": None,
    "created_at": "2026-10-28T09:00:00Z",
}


async def test_category_request_is_submitted_by_the_stock_holder_and_listed(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router = mock(be)
    post = router.post(f"{API}/catalog/category-requests/").mock(
        return_value=httpx.Response(201, json=REQUEST)
    )
    router.get(f"{API}/catalog/category-requests/").mock(
        return_value=httpx.Response(200, json=page([REQUEST]))
    )

    created = await call(
        web,
        "POST",
        "/erp/catalog/category-requests",
        {"name": " Кабельные лотки ", "parent_id": "2", "justification": "Не нашёл подходящей"},
    )
    assert created.status_code == 201
    check(created, "/erp/catalog/category-requests", "post")
    assert body_of(post) == {
        "proposed_name": "Кабельные лотки",
        "parent": 2,
        "justification": "Не нашёл подходящей",
    }

    listed = await web.client.get(
        "/api/v1/erp/catalog/category-requests", params={"status": "pending"}
    )
    assert listed.status_code == 200
    check(listed, "/erp/catalog/category-requests", "get")
    assert listed.json()["items"][0]["proposed_name"] == "Кабельные лотки"
    assert dict(router.calls.last.request.url.params)["status"] == "PENDING"


async def test_duplicate_pending_request_is_a_conflict(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/category-requests/").mock(
        return_value=httpx.Response(400, json={"detail": "CATEGORY_REQUEST_ALREADY_PENDING"})
    )
    response = await call(
        web, "POST", "/erp/catalog/category-requests", {"name": "Кабельные лотки"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "already_pending"


# --- справочники ------------------------------------------------------------------------------


async def test_lookups_collect_units_categories_currencies_and_countries(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    router = mock(be)
    router.get(f"{API}/master-data/units/").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "code": "pcs", "name": "шт"}])
    )
    router.get(f"{API}/catalog/categories/").mock(
        return_value=httpx.Response(
            200,
            json=page(
                [{"id": 2, "name": "Электро", "parent": None, "domain_type": 1, "icon": None}]
            ),
        )
    )
    router.get(f"{API}/master-data/currencies/").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "code": "USD", "symbol": "$"}])
    )
    router.get(f"{API}/master-data/countries/").mock(
        return_value=httpx.Response(200, json=[{"id": 3, "code": "UZ", "name": "Узбекистан"}])
    )

    response = await web.client.get("/api/v1/erp/catalog/lookups")

    assert response.status_code == 200
    check(response, "/erp/catalog/lookups", "get")
    body = response.json()
    assert body["units"] == [{"id": "1", "code": "pcs", "name": "шт"}]
    assert body["categories"] == [{"id": "2", "name": "Электро", "parent_id": None}]
    assert body["currencies"] == [{"code": "USD", "symbol": "$"}]
    assert body["countries"] == [{"id": "3", "name": "Узбекистан"}]


HS = {
    "id": 8,
    "code": "8536",
    "name": "Аппаратура для коммутации",
    "unit_name": "кг",
    "extra_unit_name": "",
    "level": 4,
    "valid_from": None,
    "valid_until": None,
    "is_active": True,
    "source": "manual",
}


async def test_hs_codes_exchange_rates_and_manufacturers(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router = mock(be)
    router.get(f"{API}/master-data/hs-codes/").mock(
        return_value=httpx.Response(200, json=page([HS]))
    )
    post = router.post(f"{API}/master-data/hs-codes/").mock(
        return_value=httpx.Response(201, json=HS)
    )
    router.patch(f"{API}/master-data/hs-codes/8/").mock(
        return_value=httpx.Response(200, json={**HS, "is_active": False})
    )
    router.get(f"{API}/exchange-rates/").mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": 1,
                        "currency": "USD",
                        "rate_to_uzs": "12650.5",
                        "rate_date": "2026-10-28",
                        "source": "CBU",
                    }
                ]
            ),
        )
    )
    brand = {
        "id": 2,
        "name": "Brand",
        "country": 3,
        "country_name": "Узбекистан",
        "website": "",
        "company": None,
        "is_active": True,
    }
    router.get(f"{API}/catalog/manufacturers/").mock(
        return_value=httpx.Response(200, json=page([brand]))
    )
    mpost = router.post(f"{API}/catalog/manufacturers/").mock(
        return_value=httpx.Response(201, json=brand)
    )
    router.patch(f"{API}/catalog/manufacturers/2/").mock(
        return_value=httpx.Response(200, json={**brand, "is_active": False})
    )

    listed = await web.client.get(
        "/api/v1/erp/catalog/hs-codes", params={"q": "85", "level": 4, "active": True}
    )
    check(listed, "/erp/catalog/hs-codes", "get")
    assert listed.json()["items"][0]["code"] == "8536"
    assert dict(router.calls.last.request.url.params) == {
        "q": "85",
        "level": "4",
        "active": "1",
        "page": "1",
        "page_size": "25",
    }
    created = await call(
        web, "POST", "/erp/catalog/hs-codes", {"code": "8536", "name": "Аппаратура"}
    )
    check(created, "/erp/catalog/hs-codes", "post")
    assert body_of(post) == {"code": "8536", "name": "Аппаратура"}
    closed = await call(web, "PATCH", "/erp/catalog/hs-codes/8", {"valid_until": "2026-10-27"})
    check(closed, "/erp/catalog/hs-codes/{id}", "patch")
    assert closed.json()["is_active"] is False

    rates = await web.client.get("/api/v1/erp/catalog/exchange-rates", params={"currency": "usd"})
    check(rates, "/erp/catalog/exchange-rates", "get")
    assert rates.json()["items"][0]["source"] == "CBU"

    brands = await web.client.get("/api/v1/erp/catalog/manufacturers", params={"q": "br"})
    check(brands, "/erp/catalog/manufacturers", "get")
    assert dict(router.calls.last.request.url.params)["search"] == "br"
    made = await call(
        web, "POST", "/erp/catalog/manufacturers", {"name": "Brand", "country_id": "3"}
    )
    check(made, "/erp/catalog/manufacturers", "post")
    assert body_of(mpost) == {"name": "Brand", "country": 3}
    off = await call(
        web, "PATCH", "/erp/catalog/manufacturers/2", {"is_active": False, "country_id": None}
    )
    check(off, "/erp/catalog/manufacturers/{id}", "patch")


async def test_duplicate_reference_rows_are_conflicts_with_a_reason(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    router = mock(be)
    router.post(f"{API}/master-data/hs-codes/").mock(
        return_value=httpx.Response(409, json={"detail": "HS_CODE_EXISTS"})
    )
    router.post(f"{API}/catalog/manufacturers/").mock(
        return_value=httpx.Response(400, json={"detail": "MANUFACTURER_EXISTS"})
    )

    hs = await call(web, "POST", "/erp/catalog/hs-codes", {"code": "8536", "name": "x"})
    assert hs.status_code == 409
    assert hs.json()["details"]["reason"] == "hs_code_exists"
    brand = await call(web, "POST", "/erp/catalog/manufacturers", {"name": "Brand"})
    assert brand.status_code == 409
    assert brand.json()["details"]["reason"] == "manufacturer_exists"

    router.post(f"{API}/master-data/hs-codes/").mock(
        return_value=httpx.Response(400, json={"detail": "HS_CODE_INVALID"})
    )
    bad = await call(web, "POST", "/erp/catalog/hs-codes", {"code": "853", "name": "x"})
    assert bad.status_code == 422
    assert bad.json()["details"]["fields"] == ["code"]


async def test_erp_outage_is_service_unavailable(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/items/").mock(side_effect=httpx.ConnectError("down"))
    response = await web.client.get("/api/v1/erp/catalog/items")
    assert response.status_code == 503
