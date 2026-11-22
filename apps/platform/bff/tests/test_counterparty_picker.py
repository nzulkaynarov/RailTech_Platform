"""ЕД-6 (PR-1): поле выбора контрагента — `/people/counterparties` и `.../{id}/people`.

ERP — на respx; ответ BFF проверяется по схеме platform-bff.yaml. Факт, на котором стоит выбор:
дубль ИНН ERP называет существующую компанию (`existing_id`), а BFF отдаёт этот id наружу.
"""

import json
from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.roles import custom

API = f"{ERP_URL}/api/v1"

ROLES = {
    "client": True,
    "supplier": False,
    "manufacturer": False,
    "partner": False,
    "organization": False,
}
ROW = {
    "id": 7,
    "name": "ООО Клиент Юг",
    "inn": "300000555",
    "email": "office@yug.example.uz",
    "contact_person": "Анвар Клиентов",
    "kind": "client",
    "roles": ROLES,
    "country": "Узбекистан",
    "crm_client_id": 42,
}
OTHER = {
    **ROW,
    "id": 9,
    "name": "ООО Север",
    "inn": None,
    "email": None,
    "roles": {**ROLES, "client": False, "supplier": True},
    "country": None,
    "crm_client_id": None,
}


async def test_search_passes_filters_and_maps_rows(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(
            200, json={"count": 2, "next": None, "previous": None, "results": [ROW, OTHER]}
        )
    )
    response = await web.client.get(
        "/api/v1/people/counterparties", params={"q": " 300000555 ", "role": "supplier", "limit": 5}
    )
    assert response.status_code == 200, response.text
    check(response, "/people/counterparties", "get")
    assert dict(route.calls.last.request.url.params) == {
        "q": "300000555",
        "role": "supplier",
        "limit": "5",
    }
    first, second = response.json()["items"]
    assert first == {
        "id": "7",
        "name": "ООО Клиент Юг",
        "inn": "300000555",
        "country": "Узбекистан",
        "roles": ROLES,
        "crm_client_id": 42,
        "email": "office@yug.example.uz",
    }
    assert (second["inn"], second["country"], second["email"], second["crm_client_id"]) == (
        None,
        None,
        None,
        None,
    )
    assert second["roles"]["supplier"] is True


async def test_search_default_limit_and_bounds(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    assert (await web.client.get("/api/v1/people/counterparties")).status_code == 200
    assert dict(route.calls.last.request.url.params) == {"limit": "10"}
    assert (
        await web.client.get("/api/v1/people/counterparties", params={"limit": 21})
    ).status_code == 422
    assert (
        await web.client.get("/api/v1/people/counterparties", params={"role": "boss"})
    ).status_code == 422


async def test_create_sends_role_and_returns_the_row(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    created = {
        "id": 12,
        "name": "ООО Новый",
        "inn": "301000111",
        "registration_number": None,
        "country": "Узбекистан",
        "legal_address": "Ташкент",
        "crm_client_id": None,
        "roles": {**ROLES, "client": False, "supplier": True},
        "people": [],
        "bank_accounts": [],
        "accounts_masked": True,
        "brands": [],
    }
    route = router.post(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(201, json=created)
    )
    response = await web.client.post(
        "/api/v1/people/counterparties",
        json={
            "name": "ООО Новый",
            "inn": "301000111",
            "country_id": 3,
            "address": "Ташкент",
            "role": "supplier",
        },
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 201, response.text
    check(response, "/people/counterparties", "post")
    assert json.loads(route.calls.last.request.content) == {
        "name": "ООО Новый",
        "role": "supplier",
        "tin": "301000111",
        "country_id": 3,
        "legal_address": "Ташкент",
    }
    assert response.json()["id"] == "12"
    assert response.json()["roles"]["supplier"] is True


async def test_duplicate_inn_names_the_existing_company(
    web: Web, be: Any, check: ContractChecker
) -> None:
    """ИНН уже у компании (даже невидимой в списке): 409 с её id — выбирают, а не заводят копию."""
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.post(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(409, json={"detail": "COMPANY_EXISTS", "existing_id": 55})
    )
    response = await web.client.post(
        "/api/v1/people/counterparties",
        json={"name": "Копия", "inn": "300000777"},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 409
    check(response, "/people/counterparties", "post")
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert (body["details"]["reason"], body["details"]["existing_id"]) == ("company_exists", "55")


async def test_create_validates_input_before_erp(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    route = router.post(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(201, json={})
    )
    headers = {"X-CSRF-Token": web.csrf}
    for bad in (
        {"name": "Север", "inn": "12"},
        {"name": "", "inn": "300000777"},
        {"name": "Север", "role": "client"},
        {"name": "Север", "extra": 1},
    ):
        assert (
            await web.client.post("/api/v1/people/counterparties", json=bad, headers=headers)
        ).status_code == 422
    assert not route.called


async def test_people_with_email_and_position(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/7/people/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": 2, "name": "Бекзод", "position": "", "email": None, "is_primary": True},
                    {
                        "id": 1,
                        "name": "Анвар",
                        "position": "Инженер",
                        "email": "a@yug.example.uz",
                        "is_primary": False,
                    },
                ]
            },
        )
    )
    response = await web.client.get("/api/v1/people/counterparties/7/people")
    assert response.status_code == 200, response.text
    check(response, "/people/counterparties/{id}/people", "get")
    assert response.json()["items"] == [
        {"id": "2", "name": "Бекзод", "position": None, "email": None, "is_primary": True},
        {
            "id": "1",
            "name": "Анвар",
            "position": "Инженер",
            "email": "a@yug.example.uz",
            "is_primary": False,
        },
    ]
    assert (await web.client.get("/api/v1/people/counterparties/x/people")).status_code == 422


async def test_foreign_company_people_are_404(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/99/people/").mock(
        return_value=httpx.Response(404, json={"detail": "x"})
    )
    assert (await web.client.get("/api/v1/people/counterparties/99/people")).status_code == 404


# --- права: достаточно любого из crm.clients, erp.stock, erp.calc, eds.memo.create ---


async def _both(web: Web, be: Any) -> tuple[int, int, int]:
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    router.get(f"{API}/parties/organizations/7/people/").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    router.post(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "n"})
    )
    headers = {"X-CSRF-Token": web.csrf}
    return (
        (await web.client.get("/api/v1/people/counterparties")).status_code,
        (await web.client.get("/api/v1/people/counterparties/7/people")).status_code,
        (
            await web.client.post(
                "/api/v1/people/counterparties", json={"name": "n"}, headers=headers
            )
        ).status_code,
    )


async def test_each_single_section_is_enough(web: Web, be: Any) -> None:
    for number, section in enumerate(("crm.clients", "erp.stock", "erp.calc", "eds.memo.create")):
        await web.login([custom(60 + number, f"Только {section}", {section: "full"})])
        assert await _both(web, be) == (200, 200, 201), section


async def test_read_level_reads_but_cannot_create(web: Web, be: Any) -> None:
    await web.login([custom(70, "Читатель", {"erp.stock": "read"})])
    assert await _both(web, be) == (200, 200, 403)


async def test_no_matching_section_is_forbidden(web: Web, be: Any) -> None:
    await web.login([custom(71, "Только очередь", {"dashboard.queue": "full"})])
    assert await _both(web, be) == (403, 403, 403)


async def test_picker_needs_a_session(web: Web) -> None:
    assert (await web.client.get("/api/v1/people/counterparties")).status_code == 401
    assert (await web.client.get("/api/v1/people/counterparties/7/people")).status_code == 401
    assert (
        await web.client.post("/api/v1/people/counterparties", json={"name": "n"})
    ).status_code in (401, 403)
