"""Органайзер · Люди: контакты клиентов и партнёров (FR-11, пункт 0.11; контракт BFF, тег `chats`).

ERP — на respx; ответ BFF проверяется по схеме platform-bff.yaml. ERP сам ограничивает книгой
своей компании, BFF переводит идентификаторы в строки, пустые поля — в `null`, и передаёт фильтры.
"""

from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

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
            "email": None,
            "phone": "+998901112233",
            "is_primary": True,
            "company": {"id": 7, "name": "ООО Клиент Юг"},
            "kind": "client",
        },
        {
            "id": 32,
            "name": "Дильшод Поставщиков",
            "position": "",
            "email": "d@north.example.uz",
            "phone": None,
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
        "email": None,
        "phone": "+998901112233",
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
