"""Admin · Делегирование (СОТР-2): «Что делегировано» — личный набор сотрудника из действий.

CRM — на respx (пользователи и роли в памяти); ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется перевод действий в личную роль CRM, запрет выдать больше своего, доступ по разделу
`admin` и чужой id.
"""

import json
from typing import Any

import httpx
import pytest

from app import delegation
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.roles import NAMES, ROLE_IDS, custom, ref, rid
from tests.test_admin_users import ADMIN_ID, CrmUsers, crm_user  # noqa: F401  (фикстура `crm`)
from tests.test_admin_users import crm as crm

ROLES = f"{CRM_URL}/api/v1/platform-roles"
NOW = "2026-11-26T09:00:00Z"


def crm_role_of(code: str) -> dict[str, Any]:
    full = ref(code)
    return {
        "id": full["id"],
        "code": full["code"],
        "name": full["name"],
        "description": "",
        "is_system": full["system"],
        "version": 1,
        "access": dict(full["access"]),
        "restricted_fields": list(full["restricted_fields"]),
        "employees": 1,
        "updated_at": NOW,
    }


class CrmRoles:
    """`/api/v1/platform-roles*` CRM в памяти: чтение, создание, изменение."""

    def __init__(self, be: Backends) -> None:
        self.roles: dict[int, dict[str, Any]] = {
            ROLE_IDS[c]: crm_role_of(c) for c in ("ADMIN", "DIRECTOR", "MANAGER", "SUPPLY")
        }
        self.next_id = 500
        router = be.router
        self.list_route = router.get(ROLES).mock(
            side_effect=lambda r: httpx.Response(200, json=list(self.roles.values()))
        )
        self.create_route = router.post(ROLES).mock(side_effect=self._create)
        self.patch_route = router.patch(url__regex=rf"{ROLES}/\d+$").mock(side_effect=self._patch)

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if any(r["name"].lower() == body["name"].lower() for r in self.roles.values()):
            return httpx.Response(409, json={"code": "conflict", "message": "x", "details": {}})
        self.next_id += 1
        role = {
            "id": self.next_id,
            "code": None,
            "is_system": False,
            "version": 1,
            "employees": 0,
            "updated_at": NOW,
            **body,
        }
        self.roles[self.next_id] = role
        return httpx.Response(201, json=role)

    def _patch(self, request: httpx.Request) -> httpx.Response:
        role = self.roles[int(request.url.path.rsplit("/", 1)[1])]
        body = json.loads(request.content)
        role.update({k: v for k, v in body.items() if k != "version"}, version=role["version"] + 1)
        return httpx.Response(200, json=role)

    def personal(self) -> list[dict[str, Any]]:
        return [r for r in self.roles.values() if delegation.is_personal(r)]


@pytest.fixture
def roles(be: Backends) -> CrmRoles:
    return CrmRoles(be)


# Администратор, который сам держит все разделы каталога действий, — ему можно выдавать любые
# действия
BIG_ADMIN = custom(77, "Всё делегируется", dict.fromkeys(delegation.COVERED, "full"))


async def test_catalog_lists_actions_and_presets_without_personal(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    roles.roles[900] = {
        **crm_role_of("MANAGER"),
        "id": 900,
        "name": "Личный",
        "code": None,
        "description": delegation.personal_marker("11"),
    }

    response = await web.client.get("/api/v1/admin/delegation")

    assert response.status_code == 200
    check(response, "/admin/delegation", "get")
    body = response.json()
    assert {p["name"] for p in body["presets"]} == {
        NAMES[c] for c in ("ADMIN", "DIRECTOR", "MANAGER", "SUPPLY")
    }
    manager = next(p for p in body["presets"] if p["id"] == rid("MANAGER"))
    assert "leads.work" in manager["codes"]
    assert {a["code"] for a in body["actions"]} >= {"leads.work", "admin.staff"}
    assert all(a["area"] in {x["code"] for x in body["areas"]} for a in body["actions"])


async def test_roles_list_hides_personal_sets(web: Web, crm: CrmUsers, roles: CrmRoles) -> None:
    await web.login(["ADMIN"])
    roles.roles[900] = {
        **crm_role_of("MANAGER"),
        "id": 900,
        "name": "Личный",
        "code": None,
        "description": delegation.personal_marker("11"),
    }

    listed = (await web.client.get("/api/v1/admin/roles")).json()["items"]

    assert "900" not in {r["id"] for r in listed}


async def test_employee_delegation_is_computed_from_roles(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/users/11")  # Анна: SUPPLY + MANAGER
    one = await web.client.get("/api/v1/admin/users/11/delegation")

    assert response.status_code == one.status_code == 200
    check(one, "/admin/users/{id}/delegation", "get")
    codes = set(one.json()["codes"])
    assert {"leads.work", "quote.prepare", "stock.work"} <= codes
    assert "admin.staff" not in codes


async def test_set_delegation_builds_a_personal_role_and_assigns_it(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login([BIG_ADMIN])

    response = await web.send(
        "PUT",
        "/api/v1/admin/users/11/delegation",
        json={"codes": ["leads.work", "payments.view"], "preset_id": rid("MANAGER")},
    )

    assert response.status_code == 200, response.text
    check(response, "/admin/users/{id}/delegation", "put")
    assert set(response.json()["codes"]) >= {"leads.work", "payments.view"}
    assert "stock.work" not in response.json()["codes"]  # лишнее снято
    (personal,) = roles.personal()
    assert personal["description"] == delegation.personal_marker("11")
    assert personal["access"]["crm.leads"] == "full"
    assert personal["access"]["eds.payments"] == "read"
    assert "erp.stock" not in personal["access"]
    assert crm.users[11]["platform_role_ids"] == [personal["id"]]
    # второе сохранение меняет ту же роль, а не заводит новую
    again = await web.send(
        "PUT", "/api/v1/admin/users/11/delegation", json={"codes": ["leads.work"]}
    )
    assert again.status_code == 200
    assert len(roles.personal()) == 1
    assert "eds.payments" not in roles.personal()[0]["access"]


async def test_cannot_delegate_more_than_granter_has(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])  # у ADMIN нет crm.leads

    response = await web.send(
        "PUT", "/api/v1/admin/users/12/delegation", json={"codes": ["leads.work"]}
    )

    assert response.status_code == 403
    check(response, "/admin/users/{id}/delegation", "put")
    assert response.json()["details"]["reason"] == "delegation_exceeds_own"
    assert roles.create_route.call_count == 0
    assert crm.patch_route.call_count == 0


async def test_cannot_grant_oneself_more(web: Web, crm: CrmUsers, roles: CrmRoles) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "PUT",
        f"/api/v1/admin/users/{ADMIN_ID}/delegation",
        json={"codes": ["admin.staff", "stock.work"]},
    )

    assert response.status_code == 403
    assert roles.create_route.call_count == 0


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ACCOUNTANT"])
async def test_only_admin_changes_delegation(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    write = await web.send(
        "PUT", "/api/v1/admin/users/11/delegation", json={"codes": ["leads.work"]}
    )
    read = await web.client.get("/api/v1/admin/users/11/delegation")
    catalog = await web.client.get("/api/v1/admin/delegation")

    for response in (write, read, catalog):
        assert response.status_code == 403
    check(write, "/admin/users/{id}/delegation", "put")
    assert roles.create_route.call_count == crm.patch_route.call_count == 0


async def test_director_reads_but_does_not_write(web: Web, crm: CrmUsers, roles: CrmRoles) -> None:
    await web.login(["DIRECTOR"])

    read = await web.client.get("/api/v1/admin/users/11/delegation")
    write = await web.send(
        "PUT", "/api/v1/admin/users/11/delegation", json={"codes": ["leads.work"]}
    )

    assert read.status_code == 200
    assert write.status_code == 403
    assert roles.create_route.call_count == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"codes": []},
        {"codes": ["no.such.action"]},
        {"codes": "leads.work"},
        {"codes": ["leads.work"], "x": 1},
    ],
)
async def test_invalid_delegation_is_422(
    web: Web, crm: CrmUsers, roles: CrmRoles, check: ContractChecker, payload: dict[str, Any]
) -> None:
    await web.login([BIG_ADMIN])

    response = await web.send("PUT", "/api/v1/admin/users/12/delegation", json=payload)

    assert response.status_code == 422
    check(response, "/admin/users/{id}/delegation", "put")
    assert roles.create_route.call_count == 0


async def test_foreign_or_missing_employee_is_404_and_nothing_is_written(
    web: Web, crm: CrmUsers, roles: CrmRoles
) -> None:
    await web.login(["ADMIN"])

    read = await web.client.get("/api/v1/admin/users/999/delegation")
    write = await web.send(
        "PUT", "/api/v1/admin/users/999/delegation", json={"codes": ["chats.internal"]}
    )
    bad = await web.client.get("/api/v1/admin/users/abc/delegation")

    assert read.status_code == write.status_code == 404
    assert bad.status_code == 422
    assert roles.create_route.call_count == crm.patch_route.call_count == 0
