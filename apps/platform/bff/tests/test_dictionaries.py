"""Справочники как данные (EDS-REG): каталог «вид → домен», чтение по разделам владельца, правка —
`admin: full`, тело и ответы EDS как есть, ошибки EDS в формате `Error`. EDS — на respx."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import EdsFake, eds_error_body

BASE = "/api/v1/dictionaries"
NAME = {"ru": "Письмо банка", "uz": "Bank xati", "en": "Bank letter"}
ITEM: dict[str, Any] = {
    "code": "bank",
    "name": NAME,
    "attrs": {"urgent": False, "due_days": None},
    "active": True,
    "position": 20,
    "used": True,
}
CATALOG = {
    "items": [
        {
            "kind": "letter-kinds",
            "name": {"ru": "Виды входящих документов", "uz": "Turlar", "en": "Types"},
            "closed": False,
            "attrs": [
                {
                    "key": "urgent",
                    "type": "boolean",
                    "name": NAME,
                    "minimum": None,
                    "maximum": None,
                },
                {"key": "due_days", "type": "integer", "name": NAME, "minimum": 1, "maximum": 365},
            ],
        },
        # Вид, о котором BFF не знает, на экран не попадает.
        {"kind": "secret-kinds", "name": NAME, "closed": False, "attrs": []},
    ]
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer("GET", "dictionaries", httpx.Response(200, json=CATALOG))
    fake.answer("GET", "dictionaries/letter-kinds", httpx.Response(200, json={"items": [ITEM]}))
    fake.answer("POST", "dictionaries/letter-kinds", httpx.Response(201, json=ITEM))
    fake.answer("PATCH", "dictionaries/letter-kinds/bank", httpx.Response(200, json=ITEM))
    fake.answer(
        "PUT", "dictionaries/letter-kinds/order", httpx.Response(200, json={"items": [ITEM]})
    )
    fake.answer("DELETE", "dictionaries/letter-kinds/other", httpx.Response(204))
    return fake


async def test_catalog_adds_owner_and_area(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.client.get(BASE)
    check(response, "/dictionaries", "get")
    assert [(d["kind"], d["owner"], d["area"]) for d in response.json()["items"]] == [
        ("letter-kinds", "eds", "documents")
    ]
    assert (await web.login(["REGISTRAR"])).status_code == 200
    assert (await web.client.get(BASE)).status_code == 403


async def test_items_for_letter_workers_and_admin(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    for code in ("REGISTRAR", "DIRECTOR", "ADMIN", "MANAGER_ALL"):
        assert (await web.login([code])).status_code == 200
        response = await web.client.get(f"{BASE}/letter-kinds", params={"include_hidden": "true"})
        check(response, "/dictionaries/{kind}", "get")
        assert response.json() == {"items": [ITEM]}
    assert eds.made("GET", "dictionaries/letter-kinds")[-1].url.params["include_hidden"] == "true"
    assert (await web.login(["SUPPLY"])).status_code == 200
    assert (await web.client.get(f"{BASE}/letter-kinds")).status_code == 403
    assert (await web.client.get(f"{BASE}/currencies")).status_code == 404


async def test_admin_changes_and_the_body_goes_to_eds(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    created = await web.send(
        "POST",
        f"{BASE}/letter-kinds",
        json={"name": {"ru": " Претензия "}, "attrs": {"urgent": True}},
    )
    check(created, "/dictionaries/{kind}", "post")
    assert created.status_code == 201
    [sent] = eds.made("POST", "dictionaries/letter-kinds")
    assert sent.read() == (
        b'{"name":{"ru":"\xd0\x9f\xd1\x80\xd0\xb5\xd1\x82\xd0\xb5\xd0\xbd\xd0\xb7\xd0\xb8\xd1\x8f",'
        b'"uz":"","en":""},"attrs":{"urgent":true}}'
    )
    hidden = await web.send("PATCH", f"{BASE}/letter-kinds/bank", json={"active": False})
    check(hidden, "/dictionaries/{kind}/{code}", "patch")
    assert eds.made("PATCH", "dictionaries/letter-kinds/bank")[0].read() == b'{"active":false}'
    ordered = await web.send("PUT", f"{BASE}/letter-kinds/order", json={"codes": ["bank"]})
    check(ordered, "/dictionaries/{kind}/order", "put")
    removed = await web.send("DELETE", f"{BASE}/letter-kinds/other")
    assert removed.status_code == 204


async def test_eds_conflict_keeps_the_reason(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "DELETE",
        "dictionaries/letter-kinds/bank",
        httpx.Response(
            409,
            json=eds_error_body(
                "CONFLICT",
                "Значение уже есть у писем — его можно только скрыть.",
                reason="value_in_use",
            ),
        ),
    )
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.send("DELETE", f"{BASE}/letter-kinds/bank")
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "value_in_use"
    assert response.json()["message"] == "Значение уже есть у писем — его можно только скрыть."


async def test_only_admin_full_changes(web: Web, eds: EdsFake) -> None:
    for code in ("REGISTRAR", "DIRECTOR"):
        assert (await web.login([code])).status_code == 200
        response = await web.send("POST", f"{BASE}/letter-kinds", json={"name": {"ru": "X"}})
        assert response.status_code == 403
        assert (await web.send("DELETE", f"{BASE}/letter-kinds/other")).status_code == 403
    assert eds.made("POST", "dictionaries/letter-kinds") == []
