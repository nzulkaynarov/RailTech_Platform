"""Тесты очереди смены реквизитов контрагента в BFF (FX-4)."""

import json
from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1/finance/bank-changes"
BASE = "/eds/payments/bank-changes"

RAW = {
    "id": 7,
    "company_id": 42,
    "company_name": "ООО Пример",
    "company_inn": "123456789",
    "company_archived": False,
    "status": "pending",
    "stale": False,
    "old_bank_details": "р/с 20208000123456789001",
    "new_bank_details": "р/с 20208000555566667777",
    "requested_by_name": "Админ Примеров",
    "requested_by_email": "admin@example.uz",
    "requested_ip": "203.0.113.7",
    "created_at": "2026-11-08T10:00:00+05:00",
    "decided_at": None,
    "decided_by_name": None,
    "reject_reason": None,
}


def mock(be: Any) -> respx.MockRouter:
    router: respx.MockRouter = be.router
    return router


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method,
        f"/api/v1{path}",
        json=body if body is not None else ({} if method != "GET" else None),
        headers={"X-CSRF-Token": web.csrf},
    )


async def test_list_goes_to_erp_with_filter(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])
    route = (
        mock(be)
        .get(f"{API}/")
        .mock(return_value=httpx.Response(200, json={"items": [RAW], "pending_count": 1}))
    )

    response = await call(web, "GET", f"{BASE}?status=pending")

    assert response.status_code == 200
    check(response, BASE, "get")
    assert response.json()["items"][0]["id"] == "7"
    assert response.json()["items"][0]["company_id"] == "42"
    assert route.calls.last.request.url.params["status"] == "pending"


async def test_list_is_not_captured_by_the_invoice_route(web: Web, be: Any) -> None:
    await web.login(["ACCOUNTANT"])
    mock(be).get(f"{API}/").mock(
        return_value=httpx.Response(200, json={"items": [], "pending_count": 0})
    )

    assert (await call(web, "GET", BASE)).status_code == 200


async def test_approve(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])
    mock(be).post(f"{API}/7/approve/").mock(
        return_value=httpx.Response(200, json={**RAW, "status": "approved"})
    )

    response = await call(web, "POST", f"{BASE}/7/approve")

    assert response.status_code == 200
    check(response, f"{BASE}/{{id}}/approve", "post")
    assert response.json()["status"] == "approved"


async def test_reject_sends_the_reason(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])
    route = (
        mock(be)
        .post(f"{API}/7/reject/")
        .mock(
            return_value=httpx.Response(
                200, json={**RAW, "status": "rejected", "reject_reason": "Нет письма банка"}
            )
        )
    )

    response = await call(web, "POST", f"{BASE}/7/reject", {"reason": "Нет письма банка"})

    assert response.status_code == 200
    check(response, f"{BASE}/{{id}}/reject", "post")
    assert json.loads(route.calls.last.request.content) == {"reason": "Нет письма банка"}


async def test_reject_without_a_reason_is_refused_by_the_bff(web: Web, be: Any) -> None:
    await web.login(["ACCOUNTANT"])
    route = mock(be).post(f"{API}/7/reject/")

    response = await call(web, "POST", f"{BASE}/7/reject", {"reason": ""})

    assert response.status_code in (400, 422)
    assert not route.called


async def test_conflict_carries_reason(web: Web, be: Any) -> None:
    await web.login(["ACCOUNTANT"])
    mock(be).post(f"{API}/7/approve/").mock(
        return_value=httpx.Response(409, json={"detail": "BANK_CHANGE_STALE"})
    )

    response = await call(web, "POST", f"{BASE}/7/approve")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "bank_change_stale"


async def test_role_without_payments_cannot_read_or_decide(web: Web) -> None:
    await web.login(["SUPPLY"])

    assert (await call(web, "GET", BASE)).status_code == 403
    assert (await call(web, "POST", f"{BASE}/7/approve")).status_code == 403


async def test_read_only_role_cannot_decide(web: Web) -> None:
    await web.login(["DIRECTOR"])

    assert (await call(web, "POST", f"{BASE}/7/approve")).status_code == 403
