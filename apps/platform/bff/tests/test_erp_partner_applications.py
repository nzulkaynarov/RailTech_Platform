"""Тесты очереди заявок кандидатов в партнёры в BFF (PART-ONBOARD-2, ADR-0022)."""

import json
from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
BASE = "/erp/catalog/partner-applications"

APPLICATION_RAW = {
    "id": 15,
    "source": "public",
    "status": "submitted",
    "kind": "manufacturer",
    "company_name": "ООO Металл Трейд",
    "inn": "7701234567",
    "contact_name": "Иван Металлов",
    "email": "ivan@metal.example.com",
    "phone": "+998901234567",
    "language": "ru",
    "categories_description": "Рельсовый крепеж и стрелки",
    "contract_number": "",
    "contract_date": None,
    "rejected_reason": "",
    "created_at": "2026-11-06T10:00:00+05:00",
    "reviewed_at": None,
    "matching_company_id": 9,
    "matching_company_name": "ООО Поставщик Север",
    "company_match_pending": "inn",
    "invite_delivery": None,
}

LIST_RAW = {
    "items": [APPLICATION_RAW],
    "pending_count": 1,
}


def mock(be: Any) -> respx.MockRouter:
    router: respx.MockRouter = be.router
    return router


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method,
        f"/api/v1{path}",
        json=body if body is not None else ({} if method not in ("GET", "DELETE") else None),
        headers={"X-CSRF-Token": web.csrf},
    )


async def test_list_partner_applications(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/partner-applications/").mock(
        return_value=httpx.Response(200, json=LIST_RAW)
    )
    response = await call(web, "GET", BASE)
    assert response.status_code == 200
    check(response, "/erp/catalog/partner-applications", "get")
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "15"
    assert data["items"][0]["matching_company_id"] == "9"
    assert data["pending_count"] == 1


async def test_send_contract(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    sent_raw = {
        **APPLICATION_RAW,
        "status": "contract_sent",
        "contract_number": "D-2026",
        "contract_date": "2026-11-06",
        "reviewed_at": "2026-11-06T11:00:00+05:00",
    }
    mock(be).post(f"{API}/catalog/partner-applications/15/send-contract/").mock(
        return_value=httpx.Response(200, json=sent_raw)
    )
    response = await call(
        web,
        "POST",
        f"{BASE}/15/send-contract",
        {"contract_number": "D-2026", "contract_date": "2026-11-06"},
    )
    assert response.status_code == 200
    check(response, "/erp/catalog/partner-applications/{id}/send-contract", "post")
    assert response.json()["status"] == "contract_sent"
    assert response.json()["contract_number"] == "D-2026"


async def test_approve_application(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    approved_raw = {
        **APPLICATION_RAW,
        "status": "approved",
        "contract_number": "D-2026-FIN",
        "contract_date": "2026-11-06",
        "reviewed_at": "2026-11-06T11:00:00+05:00",
    }
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/approve/")
        .mock(return_value=httpx.Response(200, json=approved_raw))
    )
    response = await call(
        web,
        "POST",
        f"{BASE}/15/approve",
        {"contract_number": "D-2026-FIN", "contract_date": "2026-11-06", "company_id": "9"},
    )
    assert response.status_code == 200
    check(response, "/erp/catalog/partner-applications/{id}/approve", "post")
    assert response.json()["status"] == "approved"
    # Проверяем, что company_id передан в ERP как int
    req_body = json.loads(route.calls.last.request.content)
    assert req_body["company_id"] == 9


async def test_reject_application(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    rejected_raw = {
        **APPLICATION_RAW,
        "status": "rejected",
        "rejected_reason": "Не наш профиль",
        "reviewed_at": "2026-11-06T11:00:00+05:00",
    }
    mock(be).post(f"{API}/catalog/partner-applications/15/reject/").mock(
        return_value=httpx.Response(200, json=rejected_raw)
    )
    response = await call(
        web,
        "POST",
        f"{BASE}/15/reject",
        {"rejected_reason": "Не наш профиль"},
    )
    assert response.status_code == 200
    check(response, "/erp/catalog/partner-applications/{id}/reject", "post")
    assert response.json()["status"] == "rejected"
    assert response.json()["rejected_reason"] == "Не наш профиль"


async def test_candidate_agreed_is_shown_as_is(web: Web, be: Any, check: ContractChecker) -> None:
    """FX-1 (к): согласованная кандидатом заявка не маскируется под новую."""
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/partner-applications/").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {**APPLICATION_RAW, "status": "candidate_agreed", "invite_delivery": "failed"}
                ],
                "pending_count": 0,
            },
        )
    )
    response = await call(web, "GET", BASE)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "candidate_agreed"
    check(response, "/erp/catalog/partner-applications", "get")
    filtered = await call(web, "GET", f"{BASE}?status=candidate_agreed")
    assert filtered.status_code == 200
    assert item["company_match_pending"] == "inn"
    assert item["invite_delivery"] == "failed"


async def test_send_contract_confirms_match_as_int(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/send-contract/")
        .mock(return_value=httpx.Response(200, json={**APPLICATION_RAW, "status": "contract_sent"}))
    )
    response = await call(web, "POST", f"{BASE}/15/send-contract", {"company_id": "9"})
    assert response.status_code == 200
    assert json.loads(route.calls.last.request.content)["company_id"] == 9


async def test_approve_passes_override_reason(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/approve/")
        .mock(return_value=httpx.Response(200, json={**APPLICATION_RAW, "status": "approved"}))
    )
    response = await call(
        web,
        "POST",
        f"{BASE}/15/approve",
        {
            "contract_number": "D-1",
            "override_reason": "Подписан на бумаге",
            "create_new_company": True,
        },
    )
    assert response.status_code == 200
    body = json.loads(route.calls.last.request.content)
    assert body["override_reason"] == "Подписан на бумаге"
    assert body["create_new_company"] is True


async def test_refusal_reason_reaches_the_screen(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/partner-applications/15/approve/").mock(
        return_value=httpx.Response(400, json={"detail": "CANDIDATE_AGREEMENT_REQUIRED"})
    )
    response = await call(web, "POST", f"{BASE}/15/approve", {"contract_number": "D-1"})
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "candidate_agreement_required"


async def test_access_control(web: Web) -> None:
    await web.login(["ADMIN"])
    resp = await call(web, "GET", BASE)
    assert resp.status_code == 403
    assert resp.json()["details"]["resource"] == "erp.stock"
