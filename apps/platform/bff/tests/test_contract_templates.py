"""«Документы · Шаблоны · Договоры» (ДОК-10): BFF переводит ответ ERP; решает ERP."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

ERP = f"{ERP_URL}/api/v1/crm/document-templates"


def erp_row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 12,
        "name": "Договор с клиентом · поставка",
        "kind_code": "CONTRACT",
        "approval_status": "approved",
        "edition": 3,
        "approved_by_name": "А. Юсупов",
        "approved_at": "2026-11-20T10:00:00+05:00",
        "submitted_at": "2026-11-19T10:00:00+05:00",
        "counterparty_kind": "client",
        "subject": "supply",
        "is_active": True,
        "is_locked": True,
        "languages": ["ru"],
        "updated_at": "2026-11-20T10:00:00+05:00",
    }
    return {**base, **over}


async def test_list_shows_status_edition_and_who_approved(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(f"{ERP}/contracts/").mock(
        return_value=httpx.Response(
            200, json=[erp_row(), erp_row(id=13, approval_status="on_approval", is_active=False)]
        )
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.client.get("/api/v1/document-templates/contracts")
    check(response, "/document-templates/contracts", "get")
    first, second = response.json()["items"]
    assert (first["status"], first["edition"], first["approved_by"], first["locked"]) == (
        "approved",
        3,
        "А. Юсупов",
        True,
    )
    assert second["status"] == "on_approval"


async def test_offered_templates_come_from_the_erp_for_the_deal(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    route = be.router.get(f"{ERP}/offered/").mock(
        return_value=httpx.Response(
            200, json={"counterparty_kind": "client", "default_id": 12, "items": [erp_row()]}
        )
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.client.get("/api/v1/document-templates/contracts/offered?deal_id=104")
    check(response, "/document-templates/contracts/offered", "get")
    assert route.calls.last.request.url.params["deal_id"] == "104"
    assert response.json()["default_id"] == "12"
    assert len(response.json()["items"]) == 1


@pytest.mark.parametrize(
    ("path", "erp_path"),
    [
        ("12/new-edition", "12/new-edition/"),
        ("12/submit", "12/submit/"),
        ("12/approve", "12/approve/"),
        ("12/return-to-draft", "12/return-to-draft/"),
    ],
)
async def test_actions_call_the_erp_operation(
    web: Web, be: Backends, check: ContractChecker, path: str, erp_path: str
) -> None:
    route = be.router.post(f"{ERP}/{erp_path}").mock(
        return_value=httpx.Response(200, json=erp_row())
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send("POST", f"/api/v1/document-templates/contracts/{path}")
    assert response.status_code in (200, 201), response.text
    check(response, f"/document-templates/contracts/{{id}}/{path.split('/')[1]}", "post")
    assert route.called


async def test_create_sends_kind_and_subject(web: Web, be: Backends) -> None:
    route = be.router.post(f"{ERP}/create-contract/").mock(
        return_value=httpx.Response(201, json=erp_row(approval_status="draft", edition=1))
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send(
        "POST",
        "/api/v1/document-templates/contracts",
        json={
            "name": "Договор с партнёром · услуги",
            "counterparty": "partner",
            "subject": "services",
        },
    )
    assert response.status_code == 201
    import json

    assert json.loads(route.calls.last.request.content) == {
        "name": "Договор с партнёром · услуги",
        "counterparty_kind": "partner",
        "subject": "services",
    }


async def test_locked_text_conflict_is_explained(web: Web, be: Backends) -> None:
    be.router.post(f"{ERP}/12/new-edition/").mock(
        return_value=httpx.Response(400, json={"detail": "TEMPLATE_EDITION_NEEDS_APPROVED"})
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send("POST", "/api/v1/document-templates/contracts/12/new-edition")
    assert response.status_code in (409, 422)
    assert "template_edition_needs_approved" in response.text


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY"])
async def test_approve_is_not_for_roles_without_the_zone(web: Web, be: Backends, role: str) -> None:
    be.router.post(f"{ERP}/12/approve/").mock(return_value=httpx.Response(200, json=erp_row()))
    assert (await web.login([role])).status_code == 200
    response = await web.send("POST", "/api/v1/document-templates/contracts/12/approve")
    assert response.status_code == 403


async def test_submit_with_unknown_placeholders_names_them(web: Web, be: Backends) -> None:
    """ПК-1: ERP не берёт на утверждение текст с неизвестными подстановками; коды идут на экран."""
    be.router.post(f"{ERP}/12/submit/").mock(
        return_value=httpx.Response(
            400,
            json={
                "detail": "TEMPLATE_UNKNOWN_PLACEHOLDERS",
                "unknown_placeholders": ["foo.bar", 7],
            },
        )
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send("POST", "/api/v1/document-templates/contracts/12/submit")
    assert response.status_code == 409
    details = response.json()["details"]
    assert details["reason"] == "template_unknown_placeholders"
    assert details["unknown_placeholders"] == ["foo.bar"]
