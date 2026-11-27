"""«Что может человек» (ДОСТ-1): `/admin/capabilities`, карточка человека, `/me/capabilities`.

CRM и EDS — на respx; ответы сверяются со схемами контракта. Права не меняются: только чтение.
"""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.eds_letters_support import EdsFake
from tests.roles import ref
from tests.test_admin_users import ADMIN_ID, crm_user, with_refs
from tests.test_admin_zones import crm_zone, person
from tests.test_eds_signing import EDS_AUTHORITY

NOW = "2026-11-27T09:00:00Z"
CODES = ("ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ACCOUNTANT")


def crm_role(code: str) -> dict[str, Any]:
    r = ref(code)
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "description": "",
        "is_system": r["system"],
        "version": 1,
        "access": r["access"],
        "restricted_fields": r["restricted_fields"],
        "employees": 1,
        "created_by": 7,
        "updated_by": 7,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.fixture
def world(be: Backends) -> dict[str, Any]:
    users = {
        ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", ("ADMIN",), position="Админ"),
        11: crm_user(11, "Анна Демова", ("MANAGER",)),
        12: crm_user(12, "Борис Директоров", ("DIRECTOR",), position="Директор"),
        13: crm_user(13, "Вера Бухгалтерова", ("ACCOUNTANT",)),
        14: crm_user(14, "Глеб Отключённый", ("MANAGER",), is_active=False),
    }
    be.router.get(f"{CRM_URL}/api/v1/users").mock(
        side_effect=lambda r: httpx.Response(200, json=[with_refs(u) for u in users.values()])
    )
    be.router.get(f"{CRM_URL}/api/v1/platform-roles").mock(
        side_effect=lambda r: httpx.Response(200, json=[crm_role(c) for c in CODES])
    )
    be.router.get(f"{CRM_URL}/api/v1/responsibility-zones").mock(
        side_effect=lambda r: httpx.Response(
            200,
            json={
                "items": [
                    crm_zone(1, "finance", responsible=person(13, "Вера Бухгалтерова"), problems=[])
                ]
            },
        )
    )
    return {"users": users}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    holder = {"crm_user_id": 12, "full_name": "Борис Директоров"}
    fake.answer(
        "GET",
        "signing/authorities",
        httpx.Response(200, json={"items": [{**EDS_AUTHORITY, "holder": holder}]}),
    )
    return fake


async def test_matrix_is_the_sum_of_roles_per_active_employee(
    web: Web, world: dict[str, Any], eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/capabilities")

    assert response.status_code == 200, response.text
    check(response, "/admin/capabilities", "get")
    body = response.json()
    by_name = {e["person"]["name"]: e for e in body["employees"]}
    assert "Глеб Отключённый" not in by_name  # отключённого в таблице нет
    assert by_name["Анна Демова"]["cells"]["leads"] == {"level": "work", "partial": False}
    assert by_name["Вера Бухгалтерова"]["cells"]["payments"]["level"] == "decide"
    assert by_name["Анна Демова"]["cells"]["staff"]["level"] == "none"
    assert by_name["Иван Тестов"]["cells"]["exceptional"]["level"] == "decide"
    assert body["signing_known"] is True
    assert [a["kinds"] for a in by_name["Борис Директоров"]["signing"]] == [
        ["letter_out", "contract"]
    ]
    assert by_name["Борис Директоров"]["signing"][0]["limit"] == {
        "amount": "10000000.00",
        "currency": "UZS",
    }
    assert by_name["Вера Бухгалтерова"]["zones"][0]["role"] == "responsible"
    codes = {(w["code"], w.get("capability")) for w in body["warnings"]}
    assert ("only_decider", "payments") in codes
    assert ("visa_without_signing", "contract") in codes  # бухгалтер визирует, подписи нет
    assert body["groups"][0]["key"] == "leads_clients"


async def test_matrix_only_reads(web: Web, world: dict[str, Any], eds: EdsFake) -> None:
    """Только чтение: после входа к CRM и EDS уходят одни GET (кроме обмена токена)."""
    await web.login(["ADMIN"])
    before = len(web.be.router.calls)
    await web.client.get("/api/v1/admin/capabilities")
    sent = [c.request for c in web.be.router.calls][before:]
    assert sent
    assert {r.method for r in sent if "/auth/" not in r.url.path} == {"GET"}


async def test_director_reads_the_matrix_but_the_signing_register_is_unknown_to_him(
    web: Web, world: dict[str, Any], eds: EdsFake
) -> None:
    eds.exchange_status = 403
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/admin/capabilities")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["signing_known"] is False  # «не известно», а не «нет права подписи»
    assert not [w for w in body["warnings"] if w["code"] == "visa_without_signing"]


async def test_the_matrix_is_closed_to_those_without_the_admin_section(
    web: Web, world: dict[str, Any]
) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get("/api/v1/admin/capabilities")).status_code == 403
    assert (await web.client.get("/api/v1/admin/users/11/capabilities")).status_code == 403


async def test_card_of_one_person(
    web: Web, world: dict[str, Any], eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/users/11/capabilities")

    assert response.status_code == 200, response.text
    check(response, "/admin/users/{id}/capabilities", "get")
    body = response.json()
    rows = {r["key"]: r for g in body["groups"] for r in g["rows"]}
    assert body["employee"]["name"] == "Анна Демова"
    assert rows["leads"]["from_roles"] == [
        {
            "id": str(ref("MANAGER")["id"]),
            "name": "Менеджер",
            "system": False,
            "code": "tpl:MANAGER",
        }
    ]
    assert rows["contract"]["level"] == "view"
    assert body["summary"]["does"]["ru"].startswith("лиды")
    assert "лиды" not in body["summary"]["lacks"]["ru"]
    contract = {a["key"]: a["on"] for lv in rows["contract"]["levels"] for a in lv["actions"]}
    assert contract["read"] is True
    assert contract["prepare"] is False


async def test_card_of_a_disabled_employee_opens(
    web: Web, world: dict[str, Any], eds: EdsFake
) -> None:
    await web.login(["ADMIN"])
    assert (await web.client.get("/api/v1/admin/users/14/capabilities")).status_code == 200
    assert (await web.client.get("/api/v1/admin/users/999/capabilities")).status_code == 404


async def test_my_capabilities_is_the_same_data_about_me(
    web: Web, be: Backends, eds: EdsFake, check: ContractChecker
) -> None:
    be.profile.update(
        deputy_user_id=12,
        deputy_name="Борис Директоров",
        deputy_from="2026-12-02",
        deputy_to="2026-12-09",
    )
    be.router.get(f"{CRM_URL}/api/v1/responsibility-zones").mock(
        return_value=httpx.Response(403, json={"code": "forbidden", "message": "x", "details": {}})
    )
    await web.login(["ACCOUNTANT"])

    response = await web.client.get("/api/v1/me/capabilities")

    assert response.status_code == 200, response.text
    check(response, "/me/capabilities", "get")
    body = response.json()
    rows = {r["key"]: r for g in body["groups"] for r in g["rows"]}
    assert rows["payments"]["level"] == "decide"
    assert rows["leads"]["level"] == "none"
    assert rows["payments"]["others"] == []
    assert body["warnings"] == []
    assert body["zones_known"] is False  # зоны читает администратор: «не известно»
    assert body["deputy"]["name"] == "Борис Директоров"


async def test_my_capabilities_works_for_everyone_with_a_session(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    eds.exchange_status = 403  # у сотрудника нет доступа к реестру подписи: «не известно»
    be.router.get(f"{CRM_URL}/api/v1/responsibility-zones").mock(
        return_value=httpx.Response(403, json={"code": "forbidden", "message": "x", "details": {}})
    )
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/me/capabilities")
    assert response.status_code == 200, response.text
    assert response.json()["signing_known"] is False
    assert "deputy" not in response.json()
