"""Очередь проверки карточек партнёров и цены партнёра в каталоге (PART-3, тег `erp-catalog`).

ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Решения о праве и о состоянии
карточки — за ERP; здесь: раздел `erp.stock` (чтение очереди — `read`, возврат — `full`), 422 до ERP
на возврат без причины и на поле замечания не из перечня, перевод отказов ERP (409 «не на проверке»,
400 с кодом), поля очереди, настройка цен партнёра.
"""

import json
from typing import Any

import httpx
import pytest

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.test_erp_catalog import ITEM, ITEM_DETAIL, call, erp_data_calls, mock

API = f"{ERP_URL}/api/v1"

REVIEW = {
    "kind": "card",
    "partner": {"id": 12, "name": "Завод Север"},
    "submitted_at": "2026-11-03T10:00:00+05:00",
    "due_at": "2026-11-04T10:00:00+05:00",
    "overdue": True,
}
WAITING_ROW = {**ITEM, "status": "REVIEW", "review": REVIEW, "completeness": 75}
PRICE = {
    "visibility": "cabinet",
    "source": "partner",
    "price": {"amount": "12500.00", "currency": "UZS"},
}
CARD = {
    **ITEM_DETAIL,
    "status": "REVIEW",
    "review": REVIEW,
    "completeness": 75,
    "catalog_price": PRICE,
}


def body_of(route: Any) -> Any:
    return json.loads(route.calls.last.request.content)


async def test_waiting_list_goes_to_erp_with_the_filter_and_keeps_deadlines(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])  # читать очередь может любой с разделом `erp.stock`
    route = (
        mock(be)
        .get(f"{API}/catalog/items/")
        .mock(
            return_value=httpx.Response(
                200, json={"count": 1, "next": None, "previous": None, "results": [WAITING_ROW]}
            )
        )
    )
    response = await web.client.get("/api/v1/erp/catalog/items", params={"review": "waiting"})
    assert response.status_code == 200
    check(response, "/erp/catalog/items", "get")
    assert route.calls.last.request.url.params["review"] == "waiting"
    row = response.json()["items"][0]
    assert row["review"]["overdue"] is True
    assert row["review"]["partner"] == {"id": "12", "name": "Завод Север"}
    assert row["completeness"] == 75
    assert response.json()["total"] == 1


async def test_ordinary_list_rows_have_no_queue_fields(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    mock(be).get(f"{API}/catalog/items/").mock(
        return_value=httpx.Response(
            200, json={"count": 1, "next": None, "previous": None, "results": [ITEM]}
        )
    )
    row = (await web.client.get("/api/v1/erp/catalog/items")).json()["items"][0]
    assert row["review"] is None
    assert row["completeness"] is None


async def test_unknown_review_filter_is_422_before_erp(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/erp/catalog/items", params={"review": "everything"})
    assert response.status_code == 422
    assert erp_data_calls(be.router) == []


async def test_card_carries_the_wait_and_the_catalog_price(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=CARD))
    response = await web.client.get("/api/v1/erp/catalog/items/4")
    assert response.status_code == 200
    check(response, "/erp/catalog/items/{id}", "get")
    body = response.json()
    assert body["review"]["due_at"] == REVIEW["due_at"]
    assert body["catalog_price"] == {
        "visibility": "cabinet",
        "source": "partner",
        "price": {"amount": "12500.00", "currency": "UZS"},
    }


async def test_return_sends_reason_and_issues_to_erp(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/catalog/items/4/return/")
        .mock(return_value=httpx.Response(200, json={**CARD, "status": "RETURNED", "review": None}))
    )
    body = {
        "reason": "Не хватает данных",
        "issues": [{"field": "manufacturer_part_number", "comment": "Укажите артикул"}],
    }
    response = await call(web, "POST", "/erp/catalog/items/4/return", body)
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/items/{id}/return", "post")
    assert body_of(route) == body
    assert response.json()["review"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": "   "},
        {"reason": "", "issues": []},
        {"issues": None},
        {"issues": [{"field": "sku", "comment": "x"}]},
        {"reason": "ок", "issues": [{"field": "price", "comment": ""}]},
        {"reason": "ок", "issues": [{"field": "price", "comment": "я" * 501}]},
        {"reason": "ок", "issues": [{"comment": "без поля"}]},
        {"reason": "ок", "issues": [{"field": "price", "comment": "x"}] * 31},
        {"reason": "ок", "extra": 1},
    ],
)
async def test_return_without_a_reason_or_with_a_wrong_field_is_422_before_erp(
    web: Web, be: Any, body: dict[str, Any]
) -> None:
    await web.login(["SUPPLY"])
    response = await call(web, "POST", "/erp/catalog/items/4/return", body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert erp_data_calls(be.router) == []


async def test_return_of_a_card_not_on_review_is_409_with_a_reason(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/items/4/return/").mock(
        return_value=httpx.Response(409, json={"detail": "PRODUCT_NOT_ON_REVIEW"})
    )
    response = await call(web, "POST", "/erp/catalog/items/4/return", {"reason": "Поздно"})
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "product_not_on_review"


async def test_erp_refusals_of_the_return_are_translated(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = mock(be).post(f"{API}/catalog/items/4/return/")
    route.mock(return_value=httpx.Response(400, json={"detail": "REVIEW_REASON_REQUIRED"}))
    refused = await call(web, "POST", "/erp/catalog/items/4/return", {"reason": "x"})
    assert refused.status_code == 422
    assert refused.json()["details"]["fields"] == ["reason"]
    route.mock(return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"}))
    forbidden = await call(web, "POST", "/erp/catalog/items/4/return", {"reason": "x"})
    assert forbidden.status_code == 403


async def test_read_level_cannot_return_a_card(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])  # `erp.stock: read`
    response = await call(web, "POST", "/erp/catalog/items/4/return", {"reason": "Нельзя"})
    assert response.status_code == 403
    assert erp_data_calls(be.router) == []


async def test_return_id_must_be_digits(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await call(web, "POST", "/erp/catalog/items/4x/return", {"reason": "x"})
    assert response.status_code == 422
    assert erp_data_calls(be.router) == []


# --- цены партнёра в каталоге ---------------------------------------------------------------------


def access(visibility: str) -> dict[str, Any]:
    return {
        "company_id": 9,
        "company_name": "ООО Поставщик Север",
        "relationship": {
            "role": "partner",
            "kind": "",
            "modules": ["my_products"],
            "catalog_price_visibility": visibility,
            "status": "active",
            "invited_at": None,
            "activated_at": None,
            "suspended_at": None,
            "responsible": None,
            "invited_by": None,
        },
        "contacts": [],
        "partner_modules": {"allowed": ["my_products"], "default": ["my_products"]},
        "cabinet_roles": ["partner"],
        "cabinet_modules": ["my_products"],
        "can_manage": True,
    }


@pytest.mark.parametrize("value", ["cabinet", "on_request", ""])
async def test_partner_price_visibility_is_sent_and_returned(
    web: Web, be: Any, check: ContractChecker, value: str
) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .patch(f"{API}/catalog/supplier-access/9/relationship/")
        .mock(return_value=httpx.Response(200, json=access(value)))
    )
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/cabinet-access/relationship",
        {"catalog_price_visibility": value},
    )
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/suppliers/{id}/cabinet-access/relationship", "patch")
    assert body_of(route) == {"catalog_price_visibility": value}
    assert response.json()["relationship"]["catalog_price_visibility"] == value


async def test_wrong_partner_price_visibility_is_422_before_erp(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/suppliers/9/cabinet-access/relationship",
        {"catalog_price_visibility": "everybody"},
    )
    assert response.status_code == 422
    assert erp_data_calls(be.router) == []
