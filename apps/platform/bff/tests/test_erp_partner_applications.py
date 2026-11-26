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
    "contract_source": "",
    "contract_template_id": None,
    "contract_template_name": None,
    "contract_template_edition": None,
    "contract_language": "",
    "contract_deviation_text": "",
    "contract_approval": "",
    "contract_approval_requested_by": None,
    "contract_approval_decided_by": None,
    "contract_approval_note": "",
    "contract_blocker": "CONTRACT_NOT_PREPARED",
    "contract_approvers": [],
    "can_decide_contract": False,
    "decision_needs_confirmation": False,
    "candidate_notes": "",
    "candidate_returned_at": None,
    "has_signed_scan": False,
    "signed_scan_at": None,
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


async def test_list_shows_the_lead_source(web: Web, be: Any, check: ContractChecker) -> None:
    """ЛП-1: заявка из карточки лида приходит с источником `lead`, а не «внешним входом»."""
    await web.login(["SUPPLY"])
    raw = {
        **APPLICATION_RAW,
        "id": 17,
        "source": "letter",
        "from_lead": True,
        "source_ref": "L-2041",
    }
    mock(be).get(f"{API}/catalog/partner-applications/").mock(
        return_value=httpx.Response(200, json={"items": [raw], "pending_count": 1})
    )
    response = await call(web, "GET", BASE)
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications", "get")
    item = response.json()["items"][0]
    assert (item["source"], item["source_ref"]) == ("lead", "L-2041")


async def test_create_from_letter(web: Web, be: Any, check: ContractChecker) -> None:
    """План 1.9: снабжение заводит заявку кандидата по входящему письму."""
    await web.login(["SUPPLY"])
    created = {**APPLICATION_RAW, "id": 16, "source": "letter", "source_ref": "ВХ-112/26"}
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/")
        .mock(return_value=httpx.Response(201, json=created))
    )
    body = {
        "company_name": "ООО Демо Колёса",
        "categories_description": "Колёсные пары",
        "contact_name": "Анвар Колёсов",
        "email": "wheels@example.com",
        "source_ref": "ВХ-112/26",
    }
    response = await call(web, "POST", BASE, body)
    assert response.status_code == 201, response.text
    check(response, "/erp/catalog/partner-applications", "post")
    assert (response.json()["source"], response.json()["source_ref"]) == ("letter", "ВХ-112/26")
    assert json.loads(route.calls.last.request.content) == body
    bad = await call(web, "POST", BASE, {**body, "email": "нет"})
    assert bad.status_code == 422
    await web.login(["MANAGER"])
    assert (await call(web, "POST", BASE, body)).status_code == 403


# --- ПД-1: договор партнёра без тупика ---------------------------------------------------


async def test_contract_options(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/partner-applications/contract-options/").mock(
        return_value=httpx.Response(
            200,
            json={
                "templates": [
                    {
                        "id": 4,
                        "name": "Договор с партнёром",
                        "edition": 2,
                        "languages": ["ru", "en"],
                        "is_default": True,
                    }
                ],
                "default_template_id": 4,
                "deviations_allowed": True,
                "approvers": ["Анвар Юристов"],
                "can_decide": False,
            },
        )
    )
    response = await call(web, "GET", f"{BASE}/contract-options")
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/contract-options", "get")
    data = response.json()
    assert data["templates"][0]["id"] == "4"
    assert data["default_template_id"] == "4"
    assert data["approvers"] == ["Анвар Юристов"]


async def test_prepare_contract_passes_template_as_int(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    prepared = {
        **APPLICATION_RAW,
        "contract_source": "template",
        "contract_template_id": 4,
        "contract_blocker": None,
    }
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/prepare-contract/")
        .mock(return_value=httpx.Response(200, json=prepared))
    )
    response = await call(
        web, "POST", f"{BASE}/15/prepare-contract", {"template_id": "4", "language": "en"}
    )
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/{id}/prepare-contract", "post")
    assert json.loads(route.calls.last.request.content) == {"template_id": 4, "language": "en"}
    assert response.json()["contract_source"] == "template"
    assert response.json()["contract_blocker"] is None


async def test_no_template_refusal_reaches_the_screen(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/partner-applications/15/prepare-contract/").mock(
        return_value=httpx.Response(400, json={"detail": "NO_APPROVED_PARTNER_TEMPLATE"})
    )
    response = await call(web, "POST", f"{BASE}/15/prepare-contract", {})
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "no_approved_partner_template"


async def test_own_file_goes_to_erp_as_is(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    waiting = {**APPLICATION_RAW, "contract_source": "upload", "contract_approval": "requested"}
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/prepare-contract/")
        .mock(return_value=httpx.Response(200, json=waiting))
    )
    response = await web.client.post(
        f"/api/v1{BASE}/15/prepare-contract-file",
        files={"file": ("our.pdf", b"%PDF-1.4 ours", "application/pdf")},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/{id}/prepare-contract-file", "post")
    assert b"%PDF-1.4 ours" in route.calls.last.request.content
    assert response.json()["contract_approval"] == "requested"
    # не multipart — отказ без обращения в ERP
    bad = await call(web, "POST", f"{BASE}/15/prepare-contract-file", {})
    assert bad.status_code == 422


async def test_contract_decision_passes_through_and_refusal_is_visible(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["LAWYER"])
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/contract-decision/")
        .mock(
            return_value=httpx.Response(
                200, json={**APPLICATION_RAW, "contract_approval": "returned"}
            )
        )
    )
    response = await call(
        web,
        "POST",
        f"{BASE}/15/contract-decision",
        {"decision": "return", "note": "Нет ответственности"},
    )
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/{id}/contract-decision", "post")
    assert json.loads(route.calls.last.request.content) == {
        "decision": "return",
        "note": "Нет ответственности",
    }
    mock(be).post(f"{API}/catalog/partner-applications/15/contract-decision/").mock(
        return_value=httpx.Response(403, json={"detail": "CONTRACT_DECISION_FORBIDDEN"})
    )
    forbidden = await call(web, "POST", f"{BASE}/15/contract-decision", {"decision": "approve"})
    assert forbidden.status_code == 403


async def test_send_blocker_reaches_the_screen(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/partner-applications/15/send-contract/").mock(
        return_value=httpx.Response(400, json={"detail": "CONTRACT_NOT_PREPARED"})
    )
    response = await call(web, "POST", f"{BASE}/15/send-contract", {})
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "contract_not_prepared"


async def test_document_is_streamed_as_an_attachment(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .get(f"{API}/catalog/partner-applications/15/document/")
        .mock(
            return_value=httpx.Response(
                200, content=b"%PDF-1.4 scan", headers={"content-type": "application/pdf"}
            )
        )
    )
    response = await web.client.get(f"/api/v1{BASE}/15/document", params={"which": "scan"})
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 scan"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('-15.pdf"')
    assert dict(route.calls.last.request.url.params) == {"which": "scan"}


async def test_legal_holder_reads_and_decides_but_does_not_run_the_queue(
    web: Web, be: Any, check: ContractChecker
) -> None:
    """Держатель «Право» (LAWYER, без `erp.stock`) видит заявки и решает по договору."""
    await web.login(["LAWYER"])
    mock(be).get(f"{API}/catalog/partner-applications/").mock(
        return_value=httpx.Response(200, json=LIST_RAW)
    )
    mock(be).get(f"{API}/catalog/partner-applications/15/document/").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        )
    )
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/contract-decision/")
        .mock(
            return_value=httpx.Response(
                200, json={**APPLICATION_RAW, "contract_approval": "approved"}
            )
        )
    )
    assert (await call(web, "GET", BASE)).status_code == 200
    assert (await web.client.get(f"/api/v1{BASE}/15/document")).status_code == 200
    decided = await call(web, "POST", f"{BASE}/15/contract-decision", {"decision": "approve"})
    assert decided.status_code == 200, decided.text
    assert json.loads(route.calls.last.request.content) == {"decision": "approve"}
    # действия снабжения закрыты
    assert (await call(web, "POST", f"{BASE}/15/send-contract", {})).status_code == 403
    assert (await call(web, "POST", f"{BASE}/15/prepare-contract", {})).status_code == 403
    assert (
        await call(web, "POST", f"{BASE}/15/approve", {"contract_number": "D-1"})
    ).status_code == 403


async def test_supply_without_legal_zone_cannot_decide(web: Web) -> None:
    await web.login(["SUPPLY"])
    response = await call(web, "POST", f"{BASE}/15/contract-decision", {"decision": "approve"})
    assert response.status_code == 403


PACKAGE_RAW = {
    "roles": [
        {
            "base_role": "partnership",
            "role_name": "Договор о партнёрстве",
            "template_id": 4,
            "name": "Договор о партнёрстве",
            "edition": 1,
            "languages": ["ru", "uz"],
        },
        {
            "base_role": "nda",
            "role_name": "Соглашение о неразглашении",
            "template_id": None,
            "name": None,
            "edition": None,
            "languages": [],
        },
    ],
    "ready": False,
}


async def test_package_options_name_the_role_without_a_template(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/partner-applications/contract-options/").mock(
        return_value=httpx.Response(
            200,
            json={
                "templates": [],
                "default_template_id": None,
                "deviations_allowed": True,
                "approvers": [],
                "can_decide": False,
                "package": PACKAGE_RAW,
            },
        )
    )
    response = await call(web, "GET", f"{BASE}/contract-options")
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/contract-options", "get")
    package = response.json()["package"]
    assert package["ready"] is False
    assert [(r["base_role"], r["template_id"]) for r in package["roles"]] == [
        ("partnership", "4"),
        ("nda", None),
    ]
    assert package["roles"][1]["role_name"] == "Соглашение о неразглашении"


async def test_prepare_package_and_card_documents(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    prepared = {
        **APPLICATION_RAW,
        "contract_source": "template",
        "contract_blocker": None,
        "package": [
            {
                "id": 7,
                "base_role": "nda",
                "title": "Соглашение о неразглашении",
                "number": "PA-2026-0015/2",
                "template_edition": 1,
                "has_candidate_file": False,
                "candidate_remark": "",
                "valid_from": None,
                "valid_until": None,
                "confidentiality_years": 3,
                "trade_secret_indefinite": False,
                "from_archive": False,
            }
        ],
    }
    route = (
        mock(be)
        .post(f"{API}/catalog/partner-applications/15/prepare-contract/")
        .mock(return_value=httpx.Response(200, json=prepared))
    )
    response = await call(web, "POST", f"{BASE}/15/prepare-contract", {"package": True})
    assert response.status_code == 200, response.text
    check(response, "/erp/catalog/partner-applications/{id}/prepare-contract", "post")
    assert json.loads(route.calls.last.request.content) == {"package": True}
    assert response.json()["package"][0]["base_role"] == "nda"
    assert response.json()["package"][0]["confidentiality_years"] == 3


async def test_package_document_is_requested_by_id(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .get(f"{API}/catalog/partner-applications/15/document/")
        .mock(
            return_value=httpx.Response(
                200, content=b"%PDF-1.4 nda", headers={"content-type": "application/pdf"}
            )
        )
    )
    response = await web.client.get(
        f"/api/v1{BASE}/15/document", params={"which": "contract", "doc": "7"}
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 nda"
    assert dict(route.calls.last.request.url.params) == {"which": "contract", "doc": "7"}
    bad = await web.client.get(f"/api/v1{BASE}/15/document", params={"doc": "x"})
    assert bad.status_code == 422
