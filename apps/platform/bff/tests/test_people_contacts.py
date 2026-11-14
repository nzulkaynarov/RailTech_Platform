"""Органайзер · Люди: контакты клиентов и партнёров (FR-11, пункт 0.11; контракт BFF, тег `chats`).

ERP — на respx; ответ BFF проверяется по схеме platform-bff.yaml. ERP сам ограничивает книгой
своей компании, BFF переводит идентификаторы в строки, пустые поля — в `null`, и передаёт фильтры.
"""

import json
from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL, ERP_URL

API = f"{ERP_URL}/api/v1"

PAGE = {
    "count": 2,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": 31,
            "name": "Анвар Клиентов",
            "position": "Главный инженер",
            "has_email": False,
            "has_phone": True,
            "is_primary": True,
            "company": {"id": 7, "name": "ООО Клиент Юг"},
            "kind": "client",
        },
        {
            "id": 32,
            "name": "Дильшод Поставщиков",
            "position": "",
            "has_email": True,
            "has_phone": False,
            "is_primary": False,
            "company": {"id": 9, "name": "ООО Поставщик Север"},
            "kind": "partner",
        },
    ],
}


async def test_people_of_clients_and_partners(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/people/").mock(return_value=httpx.Response(200, json=PAGE))
    response = await web.client.get("/api/v1/people/contacts")
    assert response.status_code == 200, response.text
    check(response, "/people/contacts", "get")
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (2, 1, 100)
    first, second = body["items"]
    assert first == {
        "id": "31",
        "name": "Анвар Клиентов",
        "position": "Главный инженер",
        "has_email": False,
        "has_phone": True,
        "is_primary": True,
        "company": {"id": "7", "name": "ООО Клиент Юг"},
        "kind": "client",
    }
    assert (second["position"], second["kind"]) == (None, "partner")
    assert dict(route.calls.last.request.url.params) == {"page": "1", "page_size": "100"}


async def test_filters_go_to_erp(web: Web, be: Any) -> None:
    await web.login(["ACCOUNTANT"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/people/").mock(
        return_value=httpx.Response(200, json={**PAGE, "count": 0, "results": []})
    )
    response = await web.client.get(
        "/api/v1/people/contacts", params={"kind": "partner", "q": "север", "page_size": 50}
    )
    assert response.status_code == 200
    assert dict(route.calls.last.request.url.params) == {
        "kind": "partner",
        "q": "север",
        "page": "1",
        "page_size": "50",
    }
    wrong = await web.client.get("/api/v1/people/contacts", params={"kind": "own"})
    assert wrong.status_code == 422


async def test_reveal_writes_journal_first_then_gives_contacts(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/people/31/").mock(
        return_value=httpx.Response(
            200,
            json={"id": 31, "name": "Анвар Клиентов", "phone": "+998901112233", "email": None},
        )
    )
    audit = router.post(f"{CRM_URL}/api/v1/audit/contact-reveal").mock(
        return_value=httpx.Response(204)
    )
    response = await web.client.post(
        "/api/v1/people/contacts/31/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 200, response.text
    check(response, "/people/contacts/{id}/reveal", "post")
    assert response.json() == {"id": "31", "phone": "+998901112233", "email": None}
    sent = json.loads(audit.calls.last.request.content)
    assert sent == {"contact": "31", "name": "Анвар Клиентов"}


async def test_no_journal_no_contacts(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/people/31/").mock(
        return_value=httpx.Response(200, json={"id": 31, "name": "Анвар", "phone": "+9989"})
    )
    router.post(f"{CRM_URL}/api/v1/audit/contact-reveal").mock(return_value=httpx.Response(500))
    response = await web.client.post(
        "/api/v1/people/contacts/31/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 503
    assert "+9989" not in response.text


# --- «Ш»: адресат письма из контрагентов ---------------------------------------------------------

ORGS = {
    "count": 2,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": 7,
            "name": "ООО Клиент Юг",
            "inn": "300000555",
            "email": "office@yug.example.uz",
            "contact_person": "Анвар Клиентов",
            "kind": "client",
        },
        {
            "id": 9,
            "name": "ООО Изготовитель",
            "inn": None,
            "email": "",
            "contact_person": None,
            "kind": "partner",
        },
    ],
}


async def test_addressees_from_counterparties(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/organizations/").mock(
        return_value=httpx.Response(200, json=ORGS)
    )
    response = await web.client.get("/api/v1/eds/addressees", params={"q": "ооо"})
    assert response.status_code == 200, response.text
    check(response, "/eds/addressees", "get")
    first, second = response.json()["items"]
    assert first == {
        "id": "7",
        "name": "ООО Клиент Юг",
        "inn": "300000555",
        "email": "office@yug.example.uz",
        "attention": "Анвар Клиентов",
        "kind": "client",
    }
    assert (second["inn"], second["email"], second["attention"]) == (None, None, None)
    assert dict(route.calls.last.request.url.params) == {"q": "ооо", "page_size": "10"}


async def test_addressees_need_two_letters(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/eds/addressees", params={"q": "о"})
    assert response.status_code == 422


async def test_addressees_need_a_session(web: Web) -> None:
    response = await web.client.get("/api/v1/eds/addressees", params={"q": "ооо"})
    assert response.status_code == 401
