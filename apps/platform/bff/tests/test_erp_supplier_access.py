"""Доступ поставщика в кабинет — блок карточки поставщика (контракт BFF, тег `erp-catalog`; PART-1,
ADR-0022).

ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Права на операции решает ERP
(`supply.manage`); здесь — раздел `erp.stock` (изменения только при `full`, ERP до этого не
вызывается), перевод идентификаторов и отказов ERP, и то, что ссылки входа и кода в ответах нет.
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
BASE = "/erp/catalog/suppliers/9/cabinet-access"

RELATIONSHIP = {
    "role": "partner",
    "kind": "supplier",
    "modules": ["my_products", "catalog_requests"],
    "status": "invited",
    "invited_at": "2026-11-04T10:00:00+05:00",
    "activated_at": None,
    "suspended_at": None,
    "responsible": {"id": 3, "name": "Менеджер Снабжения"},
    "invited_by": {"id": 3, "name": "Менеджер Снабжения"},
}
CONTACT = {
    "id": 21,
    "name": "Dilshod Supplier",
    "email": "dilshod@supplier-north.example.uz",
    "phone": "+998901112233",
    "language": "uz",
    "can_act": True,
    "invited_at": None,
    "last_login_at": None,
}
STATE = {
    "company_id": 9,
    "company_name": "ООО Поставщик Север",
    "relationship": RELATIONSHIP,
    "contacts": [CONTACT],
    "partner_modules": {
        "allowed": ["my_products", "catalog_requests"],
        "default": ["my_products", "catalog_requests"],
    },
    "cabinet_roles": ["partner"],
    "cabinet_modules": ["my_products", "catalog_requests"],
    "crm_client": {"status": "requested", "crm_client_id": None},
    "can_manage": True,
}
EMPTY = {**STATE, "relationship": None, "contacts": [], "cabinet_roles": [], "cabinet_modules": []}


def mock(be: Any) -> respx.MockRouter:
    router: respx.MockRouter = be.router
    return router


def body_of(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


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


WRITES = (
    ("POST", f"{BASE}/contacts"),
    ("PATCH", f"{BASE}/contacts/21"),
    ("PATCH", f"{BASE}/relationship"),
    ("POST", f"{BASE}/invite"),
    ("POST", f"{BASE}/suspend"),
    ("POST", f"{BASE}/crm-client/confirm"),
    ("POST", f"{BASE}/crm-client/reject"),
)


async def test_administrator_has_no_erp_stock_and_never_reaches_erp(web: Web, be: Any) -> None:
    await web.login(["ADMIN"])
    for method, path in (("GET", BASE), *WRITES):
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"]["resource"] == "erp.stock", (method, path)
    assert erp_data_calls(be.router) == []


@pytest.mark.parametrize("role", ["MANAGER", "ACCOUNTANT"])
async def test_read_level_reads_but_cannot_change(web: Web, be: Any, role: str) -> None:
    await web.login([role])
    mock(be).get(f"{API}/catalog/supplier-access/9/").mock(
        return_value=httpx.Response(200, json={**STATE, "can_manage": False})
    )
    assert (await call(web, "GET", BASE)).status_code == 200
    calls_before = len(erp_data_calls(be.router))
    for method, path in WRITES:
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["details"] == {"resource": "erp.stock", "need": "full"}
    assert len(erp_data_calls(be.router)) == calls_before


async def test_write_without_csrf_is_rejected(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await web.client.post(f"/api/v1{BASE}/suspend")
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert erp_data_calls(be.router) == []


async def test_state_translates_ids_and_matches_the_contract(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/supplier-access/9/").mock(
        return_value=httpx.Response(200, json=STATE)
    )

    response = await call(web, "GET", BASE)

    assert response.status_code == 200
    check(response, "/erp/catalog/suppliers/{id}/cabinet-access", "get")
    body = response.json()
    assert body["company_id"] == "9"
    assert body["contacts"][0]["id"] == "21"
    assert body["relationship"]["responsible"] == {"id": "3", "name": "Менеджер Снабжения"}
    assert body["relationship"]["modules"] == ["my_products", "catalog_requests"]
    assert body["cabinet_roles"] == ["partner"]


async def test_state_without_relationship(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    mock(be).get(f"{API}/catalog/supplier-access/9/").mock(
        return_value=httpx.Response(200, json=EMPTY)
    )
    response = await call(web, "GET", BASE)
    check(response, "/erp/catalog/suppliers/{id}/cabinet-access", "get")
    assert response.json()["relationship"] is None
    assert response.json()["cabinet_roles"] == []


@pytest.mark.parametrize(
    ("erp", "expected"),
    [
        ({"status": "linked", "crm_client_id": 58}, {"status": "linked", "crm_client_id": "58"}),
        (
            {"status": "conflict", "crm_client_id": 88},
            {"status": "conflict", "crm_client_id": "88"},
        ),
        (
            {"status": "requested", "crm_client_id": None},
            {"status": "requested", "crm_client_id": None},
        ),
        (
            {"status": "pending_confirmation", "crm_client_id": 90},
            {"status": "pending_confirmation", "crm_client_id": "90"},
        ),
        (
            {"status": "held", "crm_client_id": 4001},
            {"status": "held", "crm_client_id": "4001"},
        ),
        (
            None,
            {"status": "none", "crm_client_id": None},
        ),  # ERP без поля (старая версия): «не просили»
        ({"status": "weird", "crm_client_id": 1}, {"status": "none", "crm_client_id": None}),
    ],
)
async def test_crm_client_of_the_partner_is_shown_with_a_string_id(
    web: Web, be: Any, check: ContractChecker, erp: Any, expected: Any
) -> None:
    """PART-CRM: «клиент в CRM» — заведён, ожидает, конфликт; id клиента CRM — строкой."""
    await web.login(["SUPPLY"])
    state = {k: v for k, v in STATE.items() if k != "crm_client"}
    if erp is not None:
        state["crm_client"] = erp
    mock(be).get(f"{API}/catalog/supplier-access/9/").mock(
        return_value=httpx.Response(200, json=state)
    )

    response = await call(web, "GET", BASE)

    check(response, "/erp/catalog/suppliers/{id}/cabinet-access", "get")
    assert response.json()["crm_client"] == {"crm_client_name": None, "inn": None, **expected}


async def test_contact_create_and_update_forward_only_sent_fields(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router = mock(be)
    create = router.post(f"{API}/catalog/supplier-access/9/contacts/").mock(
        return_value=httpx.Response(201, json=CONTACT)
    )
    update = router.patch(f"{API}/catalog/supplier-access/9/contacts/21/").mock(
        return_value=httpx.Response(200, json={**CONTACT, "name": "Dilshod K."})
    )

    created = await call(
        web,
        "POST",
        f"{BASE}/contacts",
        {"name": "Dilshod Supplier", "email": CONTACT["email"], "language": "uz"},
    )
    updated = await call(web, "PATCH", f"{BASE}/contacts/21", {"name": "Dilshod K."})

    assert created.status_code == 201
    assert created.json()["id"] == "21"
    check(created, "/erp/catalog/suppliers/{id}/cabinet-access/contacts", "post")
    assert body_of(create) == {
        "name": "Dilshod Supplier",
        "email": CONTACT["email"],
        "language": "uz",
    }
    assert updated.status_code == 200
    assert body_of(update) == {"name": "Dilshod K."}
    check(updated, "/erp/catalog/suppliers/{id}/cabinet-access/contacts/{contact_id}", "patch")


async def test_contact_input_is_validated_before_erp(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    for body in (
        {"name": "X"},
        {"name": "X", "email": "a@b.uz", "language": "de"},
        {"name": "", "email": "a@b.uz"},
    ):
        assert (await call(web, "POST", f"{BASE}/contacts", body)).status_code == 422
    assert (await call(web, "PATCH", f"{BASE}/contacts/21", {})).status_code == 422
    assert erp_data_calls(be.router) == []


async def test_invite_sends_contact_id_as_number_and_returns_state_without_secrets(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/catalog/supplier-access/9/invite/")
        .mock(return_value=httpx.Response(200, json=STATE))
    )

    response = await call(
        web,
        "POST",
        f"{BASE}/invite",
        {"contact_id": "21", "modules": ["my_products"], "kind": "principal"},
    )

    assert response.status_code == 200
    check(response, "/erp/catalog/suppliers/{id}/cabinet-access/invite", "post")
    assert body_of(route) == {"contact_id": 21, "modules": ["my_products"], "kind": "principal"}
    assert "auth/magic" not in response.text
    assert "token" not in response.text.lower()


async def test_rights_update_and_suspend(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["DIRECTOR"])
    router = mock(be)
    rights = router.patch(f"{API}/catalog/supplier-access/9/relationship/").mock(
        return_value=httpx.Response(200, json=STATE)
    )
    suspend = router.post(f"{API}/catalog/supplier-access/9/suspend/").mock(
        return_value=httpx.Response(
            200, json={**STATE, "relationship": {**RELATIONSHIP, "status": "suspended"}}
        )
    )

    one = await call(web, "PATCH", f"{BASE}/relationship", {"modules": ["my_products"]})
    two = await call(web, "POST", f"{BASE}/suspend")

    assert one.status_code == 200
    assert body_of(rights) == {"modules": ["my_products"]}
    check(one, "/erp/catalog/suppliers/{id}/cabinet-access/relationship", "patch")
    assert two.json()["relationship"]["status"] == "suspended"
    assert suspend.called
    check(two, "/erp/catalog/suppliers/{id}/cabinet-access/suspend", "post")


UNVERIFIED = {
    "status": "unverified",
    "crm_client_id": 4001,
    "crm_client_name": "ООО Чужой Клиент",
    "inn": "300000555",
}


async def test_unverified_crm_client_is_shown_and_decided_through_erp(
    web: Web, be: Any, check: ContractChecker
) -> None:
    """PART-CRM: «Найден клиент CRM по ИНН. Это та же компания?» — «Да» и «Нет» уходят в ERP."""
    await web.login(["SUPPLY"])
    router = mock(be)
    router.get(f"{API}/catalog/supplier-access/9/").mock(
        return_value=httpx.Response(200, json={**STATE, "crm_client": UNVERIFIED})
    )
    yes = router.post(f"{API}/catalog/supplier-access/9/crm-client/confirm/").mock(
        return_value=httpx.Response(
            200, json={**STATE, "crm_client": {"status": "linked", "crm_client_id": 4001}}
        )
    )
    no = router.post(f"{API}/catalog/supplier-access/9/crm-client/reject/").mock(
        return_value=httpx.Response(
            200, json={**STATE, "crm_client": {"status": "requested", "crm_client_id": None}}
        )
    )

    state = await call(web, "GET", BASE)
    one = await call(web, "POST", f"{BASE}/crm-client/confirm")
    two = await call(web, "POST", f"{BASE}/crm-client/reject")

    check(state, "/erp/catalog/suppliers/{id}/cabinet-access", "get")
    assert state.json()["crm_client"] == {**UNVERIFIED, "crm_client_id": "4001"}
    check(one, "/erp/catalog/suppliers/{id}/cabinet-access/crm-client/confirm", "post")
    assert one.json()["crm_client"] == {
        "status": "linked",
        "crm_client_id": "4001",
        "crm_client_name": None,
        "inn": None,
    }
    check(two, "/erp/catalog/suppliers/{id}/cabinet-access/crm-client/reject", "post")
    assert two.json()["crm_client"]["status"] == "requested"
    assert yes.called
    assert no.called


async def test_nothing_to_verify_keeps_the_erp_reason(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/supplier-access/9/crm-client/confirm/").mock(
        return_value=httpx.Response(409, json={"detail": "NOTHING_TO_VERIFY"})
    )
    response = await call(web, "POST", f"{BASE}/crm-client/confirm")
    check(response, "/erp/catalog/suppliers/{id}/cabinet-access/crm-client/confirm", "post")
    assert response.status_code == 409


async def test_module_outside_the_template_is_refused_before_erp(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    response = await call(web, "PATCH", f"{BASE}/relationship", {"modules": ["quotes"]})
    assert response.status_code == 422
    assert erp_data_calls(be.router) == []


@pytest.mark.parametrize(
    ("erp_status", "erp_body", "status", "reason"),
    [
        (409, {"detail": "CONTACT_EXISTS"}, 409, "contact_exists"),
        (409, {"detail": "CONTACT_EMAIL_AMBIGUOUS"}, 409, "contact_email_ambiguous"),
        (400, {"detail": "EMAIL_DELIVERY_FAILED"}, 422, "email_delivery_failed"),
        (400, {"detail": "MODULE_NOT_ALLOWED"}, 422, "module_not_allowed"),
        (404, {"detail": "NOT_FOUND"}, 404, None),
        (403, {"detail": "ROLE_NOT_PERMITTED"}, 403, None),
    ],
)
async def test_erp_refusals_are_translated(
    web: Web, be: Any, erp_status: int, erp_body: dict[str, str], status: int, reason: str | None
) -> None:
    await web.login(["SUPPLY"])
    mock(be).post(f"{API}/catalog/supplier-access/9/invite/").mock(
        return_value=httpx.Response(erp_status, json=erp_body)
    )

    response = await call(web, "POST", f"{BASE}/invite", {"contact_id": "21"})

    assert response.status_code == status
    if reason:
        assert response.json()["details"]["reason"] == reason
