"""Справочники как данные (EDS-REG): каталог «вид → домен», чтение по разделам владельца, правка —
`admin: full`, тело и ответы EDS как есть, ошибки EDS в формате `Error`. EDS — на respx."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
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


CRM_CATALOG = {
    "items": [
        {
            "kind": "mail-types",
            "name": {"ru": "Типы входящих писем", "uz": "Turlar", "en": "Mail types"},
            "closed": False,
            "attrs": [
                {
                    "key": "default_action",
                    "type": "choice",
                    "name": NAME,
                    "minimum": None,
                    "maximum": None,
                    "options": [{"value": "create_lead", "name": NAME}],
                }
            ],
        }
    ]
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    be.router.get(f"{CRM_URL}/api/v1/dictionaries").mock(
        return_value=httpx.Response(200, json=CRM_CATALOG)
    )
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
    assert response.json()["unavailable"] == []
    assert [(d["kind"], d["owner"], d["area"]) for d in response.json()["items"]] == [
        ("letter-kinds", "eds", "documents"),
        ("mail-types", "crm", "mail"),
    ]
    [choice] = response.json()["items"][1]["attrs"]
    assert (choice["type"], choice["options"][0]["value"]) == ("choice", "create_lead")
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


async def test_catalog_is_partial_when_crm_is_down_and_all_down_is_an_error(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    be.router.get(f"{CRM_URL}/api/v1/dictionaries").mock(return_value=httpx.Response(503))
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.client.get(BASE)
    assert response.status_code == 200
    assert [d["kind"] for d in response.json()["items"]] == ["letter-kinds"]
    assert response.json()["unavailable"] == ["crm"]

    eds.answer("GET", "dictionaries", httpx.Response(503))
    assert (await web.client.get(BASE)).status_code == 503


async def test_catalog_gives_the_letter_kind_field_options_from_eds(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "GET",
        "dictionaries/letter-kinds",
        httpx.Response(
            200,
            json={
                "items": [
                    ITEM,
                    {**ITEM, "code": "old", "active": False, "name": {**NAME, "ru": "Старый"}},
                ]
            },
        ),
    )
    be_catalog = {
        "items": [
            {
                "kind": "mail-types",
                "name": NAME,
                "closed": False,
                "attrs": [
                    {
                        "key": "letter_kind",
                        "type": "choice",
                        "name": NAME,
                        "options": [],
                        "required": False,
                    }
                ],
            }
        ]
    }
    web.be.router.get(f"{CRM_URL}/api/v1/dictionaries").mock(
        return_value=httpx.Response(200, json=be_catalog)
    )
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.client.get(BASE)
    mail = next(d for d in response.json()["items"] if d["kind"] == "mail-types")
    [attr] = mail["attrs"]
    assert (attr["required"], [o["value"] for o in attr["options"]]) == (False, ["bank"])
