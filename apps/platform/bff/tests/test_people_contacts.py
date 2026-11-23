"""Органайзер · Люди: контакты клиентов и партнёров (FR-11, пункт 0.11; контракт BFF, тег `chats`).

ERP — на respx; ответ BFF проверяется по схеме platform-bff.yaml. ERP сам ограничивает книгой
своей компании, BFF переводит идентификаторы в строки, пустые поля — в `null`, и передаёт фильтры.
"""

import json
from typing import Any

import httpx
import pytest
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


# --- Сотрудники: контакты по нажатию с записью в журнал (решение 10.11) --------------------------

STAFF_CONTACTS = {"id": 7, "phone": "+998901112233", "email": "ivan@railtech.example"}
ROLES = [
    "ADMIN",
    "DIRECTOR",
    "MANAGER",
    "SUPPLY",
    "ENGINEER",
    "ACCOUNTANT",
    "REGISTRAR",
    "MANAGER_ALL",
    "LAWYER",
]


@pytest.mark.parametrize("role", ROLES)
async def test_every_staff_role_reveals_colleague_contacts_via_the_crm_journal(
    web: Web, be: Any, check: ContractChecker, role: str
) -> None:
    await web.login([role])
    router: respx.MockRouter = be.router
    route = router.post(f"{CRM_URL}/api/v1/staff/7/contacts").mock(
        return_value=httpx.Response(200, json=STAFF_CONTACTS)
    )
    response = await web.client.post(
        "/api/v1/people/staff/7/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 200, response.text
    check(response, "/people/staff/{id}/reveal", "post")
    assert response.json() == {
        "id": "7",
        "phone": "+998901112233",
        "email": "ivan@railtech.example",
    }
    assert route.call_count == 1


async def test_staff_contacts_are_not_given_when_crm_refuses(web: Web, be: Any) -> None:
    """Журнал и ответ — одна транзакция CRM: отказ или недоступность — контактов нет."""
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.post(f"{CRM_URL}/api/v1/staff/7/contacts").mock(return_value=httpx.Response(500))
    response = await web.client.post(
        "/api/v1/people/staff/7/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code >= 500
    assert "998901112233" not in response.text
    router.post(f"{CRM_URL}/api/v1/staff/8/contacts").mock(
        return_value=httpx.Response(404, json={"detail": "user not found"})
    )
    gone = await web.client.post(
        "/api/v1/people/staff/8/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert gone.status_code == 404


async def test_staff_reveal_needs_session_and_a_numeric_id(web: Web, be: Any) -> None:
    anonymous = await web.client.post("/api/v1/people/staff/7/reveal")
    assert anonymous.status_code in (401, 403)
    await web.login(["MANAGER"])
    bad = await web.client.post("/api/v1/people/staff/x/reveal", headers={"X-CSRF-Token": web.csrf})
    assert bad.status_code == 422


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


# --- Карточка контрагента: одна компания во всех ролях (ADR-0028, СУЩ-2.5) -----------------------

CARD = {
    "id": 9,
    "name": "ООО Поставщик Север",
    "inn": "300000777",
    "registration_number": None,
    "country": "Узбекистан",
    "legal_address": None,
    "crm_client_id": 42,
    "roles": {
        "client": True,
        "supplier": True,
        "manufacturer": False,
        "partner": False,
        "organization": False,
    },
    "people": [
        {
            "id": 31,
            "name": "Рустам Ахмедов",
            "position": "Снабжение",
            "is_primary": True,
            "has_cabinet": False,
            "has_phone": True,
            "has_email": False,
        }
    ],
    "bank_accounts": [
        {
            "id": 5,
            "currency": "UZS",
            "bank_name": "АКБ Образец",
            "bank_country": "UZ",
            "account": "…4567",
            "mfo": "00440",
            "swift": "",
            "is_default": True,
        }
    ],
    "accounts_masked": True,
    "brands": [{"id": 3, "name": "PL-Rail"}],
}


async def test_counterparty_card_by_company_and_by_client(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/9/").mock(return_value=httpx.Response(200, json=CARD))
    router.get(f"{API}/parties/crm-clients/42/organization/").mock(
        return_value=httpx.Response(200, json=CARD)
    )
    router.get(f"{API}/parties/crm-clients/77/organization/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )

    card = await web.client.get("/api/v1/people/counterparties/9")
    assert card.status_code == 200, card.text
    check(card, "/people/counterparties/{id}", "get")
    body = card.json()
    assert (body["id"], body["crm_client_id"], body["people"][0]["id"]) == ("9", 42, "31")
    assert body["roles"] == {
        "client": True,
        "supplier": True,
        "manufacturer": False,
        "partner": False,
        "organization": False,
    }
    assert body["bank_accounts"][0]["account"] == "…4567"
    by_client = await web.client.get("/api/v1/people/clients/42/counterparty")
    check(by_client, "/people/clients/{id}/counterparty", "get")
    assert by_client.json()["id"] == "9"
    assert (await web.client.get("/api/v1/people/clients/77/counterparty")).status_code == 404


async def test_counterparty_roles_are_marks(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    roles = {
        "client": True,
        "supplier": True,
        "manufacturer": True,
        "partner": False,
        "organization": False,
    }
    marked = {**CARD, "roles": roles}
    route = router.post(f"{API}/parties/organizations/9/roles/").mock(
        side_effect=lambda request: (
            httpx.Response(200, json=marked)
            if json.loads(request.content)["on"]
            else httpx.Response(409, json={"detail": "ROLE_IN_USE"})
        )
    )
    headers = {"X-CSRF-Token": web.csrf}
    on = await web.client.post(
        "/api/v1/people/counterparties/9/roles",
        json={"role": "manufacturer", "on": True},
        headers=headers,
    )
    assert on.status_code == 200, on.text
    check(on, "/people/counterparties/{id}/roles", "post")
    assert on.json()["roles"]["manufacturer"] is True
    assert json.loads(route.calls.last.request.content) == {"role": "manufacturer", "on": True}
    off = await web.client.post(
        "/api/v1/people/counterparties/9/roles",
        json={"role": "supplier", "on": False},
        headers=headers,
    )
    assert off.status_code == 409
    assert off.json()["details"]["reason"] == "role_in_use"


async def test_manager_cannot_mark_roles(web: Web) -> None:
    await web.login(["MANAGER"])
    response = await web.client.post(
        "/api/v1/people/counterparties/9/roles",
        json={"role": "manufacturer", "on": True},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 403


# --- СУЩ-2.6: организация-адресат из письма ---------------------------------------------


async def test_addressee_organization_is_created_from_the_letter(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    roles = {
        "client": False,
        "supplier": False,
        "manufacturer": False,
        "partner": False,
        "organization": True,
    }
    created = {**CARD, "id": 12, "name": "Таможенный комитет", "inn": "200000123", "roles": roles}
    route = router.post(f"{API}/parties/organizations/").mock(
        side_effect=lambda request: (
            httpx.Response(409, json={"detail": "COMPANY_EXISTS"})
            if json.loads(request.content)["tin"] == "300000777"
            else httpx.Response(201, json=created)
        )
    )
    headers = {"X-CSRF-Token": web.csrf}
    response = await web.client.post(
        "/api/v1/eds/addressees",
        json={"name": "Таможенный комитет", "inn": "200000123", "legal_address": "Ташкент"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    check(response, "/eds/addressees", "post")
    assert response.json() == {
        "id": "12",
        "name": "Таможенный комитет",
        "inn": "200000123",
        "email": None,
        "attention": None,
        "kind": "partner",
    }
    assert json.loads(route.calls.last.request.content) == {
        "name": "Таможенный комитет",
        "tin": "200000123",
        "legal_address": "Ташкент",
    }
    taken = await web.client.post(
        "/api/v1/eds/addressees", json={"name": "Север", "inn": "300000777"}, headers=headers
    )
    assert taken.status_code == 409
    assert taken.json()["details"]["reason"] == "company_exists"
    wrong = await web.client.post(
        "/api/v1/eds/addressees", json={"name": "Север", "inn": "12"}, headers=headers
    )
    assert wrong.status_code == 422


# --- СУЩ-2.7: реквизиты контрагента ведёт ERP ---------------------------------------


async def test_counterparty_requisites_go_to_erp(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    edited = {**CARD, "name": "ООО Поставщик Север-2", "inn": "300000778"}
    route = router.patch(f"{API}/parties/organizations/9/").mock(
        side_effect=lambda request: (
            httpx.Response(409, json={"detail": "COMPANY_EXISTS"})
            if json.loads(request.content).get("tin") == "300000999"
            else httpx.Response(200, json=edited)
        )
    )
    headers = {"X-CSRF-Token": web.csrf}
    ok = await web.client.patch(
        "/api/v1/people/counterparties/9",
        json={"name": "ООО Поставщик Север-2", "inn": "300000778"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    check(ok, "/people/counterparties/{id}", "patch")
    assert ok.json()["name"] == "ООО Поставщик Север-2"
    assert json.loads(route.calls.last.request.content) == {
        "name": "ООО Поставщик Север-2",
        "tin": "300000778",
    }
    taken = await web.client.patch(
        "/api/v1/people/counterparties/9", json={"inn": "300000999"}, headers=headers
    )
    assert taken.status_code == 409
    assert taken.json()["details"]["reason"] == "company_exists"
    bad = await web.client.patch(
        "/api/v1/people/counterparties/9", json={"inn": "12"}, headers=headers
    )
    assert bad.status_code == 422


async def test_accountant_cannot_edit_counterparty_requisites(web: Web) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.client.patch(
        "/api/v1/people/counterparties/9", json={"name": "X"}, headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 403


# --- Х-8: «Не работать» у контрагента ----------------------------------------------------------

MARK = {
    "reason": "Дважды не оплатил отгрузку",
    "set_by": "Менеджер Демо",
    "set_at": "2026-11-23T09:30:00Z",
    "until": None,
}


async def test_do_not_work_is_set_and_removed_in_erp(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    url = f"{API}/parties/organizations/9/do-not-work/"
    post = router.post(url).mock(
        return_value=httpx.Response(200, json={**CARD, "do_not_work": MARK})
    )
    delete = router.delete(url).mock(
        return_value=httpx.Response(200, json={**CARD, "do_not_work": None})
    )
    headers = {"X-CSRF-Token": web.csrf}

    marked = await web.client.post(
        "/api/v1/people/counterparties/9/do-not-work",
        json={"reason": "Дважды не оплатил отгрузку", "until": "2026-12-31"},
        headers=headers,
    )
    assert marked.status_code == 200, marked.text
    check(marked, "/people/counterparties/{id}/do-not-work", "post")
    assert marked.json()["do_not_work"]["reason"] == "Дважды не оплатил отгрузку"
    assert marked.json()["do_not_work"]["set_by"] == "Менеджер Демо"
    assert json.loads(post.calls.last.request.content) == {
        "reason": "Дважды не оплатил отгрузку",
        "until": "2026-12-31",
    }

    removed = await web.client.delete(
        "/api/v1/people/counterparties/9/do-not-work", headers=headers
    )
    assert removed.status_code == 200, removed.text
    check(removed, "/people/counterparties/{id}/do-not-work", "delete")
    assert removed.json()["do_not_work"] is None
    assert delete.called


async def test_do_not_work_needs_a_reason_and_the_requisites_section(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    headers = {"X-CSRF-Token": web.csrf}
    empty = await web.client.post(
        "/api/v1/people/counterparties/9/do-not-work", json={"reason": ""}, headers=headers
    )
    assert empty.status_code == 422
    # ERP отказала по причине: её код и поле доходят как есть
    router: respx.MockRouter = be.router
    router.post(f"{API}/parties/organizations/9/do-not-work/").mock(
        return_value=httpx.Response(400, json={"detail": "UNTIL_PAST"})
    )
    past = await web.client.post(
        "/api/v1/people/counterparties/9/do-not-work",
        json={"reason": "Спор", "until": "2020-01-01"},
        headers=headers,
    )
    assert past.status_code == 422
    assert past.json()["details"]["fields"] == ["until"]


async def test_accountant_cannot_mark_do_not_work(web: Web) -> None:
    await web.login(["ACCOUNTANT"])
    headers = {"X-CSRF-Token": web.csrf}
    marked = await web.client.post(
        "/api/v1/people/counterparties/9/do-not-work", json={"reason": "Спор"}, headers=headers
    )
    assert marked.status_code == 403
    cleared = await web.client.delete(
        "/api/v1/people/counterparties/9/do-not-work", headers=headers
    )
    assert cleared.status_code == 403


async def test_erp_refusal_for_a_marked_company_names_the_reason_and_who(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    router.patch(f"{API}/parties/organizations/9/").mock(
        return_value=httpx.Response(
            409,
            json={"detail": "COMPANY_DO_NOT_WORK", "company_id": 9, "do_not_work": MARK},
        )
    )
    response = await web.client.patch(
        "/api/v1/people/counterparties/9", json={"name": "X"}, headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 409
    details = response.json()["details"]
    assert details["reason"] == "company_do_not_work"
    assert details["do_not_work"]["reason"] == "Дважды не оплатил отгрузку"
    assert details["do_not_work"]["set_by"] == "Менеджер Демо"
