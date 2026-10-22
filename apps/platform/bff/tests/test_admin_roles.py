"""Admin · Ролевая матрица (R-2, ADR-0012): `/admin/roles*`, повтор приглашения.

CRM — на respx (`/api/v1/platform-roles*` R-1); ответы BFF проверяются по схемам platform-bff.yaml.
Решения (системная роль, роль с сотрудниками, последний администратор, каталог) — за CRM: здесь
проверяется перевод в контракт и то, что BFF ничего не решает сам.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.test_admin_users import CrmUsers, crm_user

ROLES = f"{CRM_URL}/api/v1/platform-roles"
NOW = "2026-10-23T09:00:00Z"


def crm_role(role_id: int, name: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": role_id,
        "code": None,
        "name": name,
        "description": "",
        "is_system": False,
        "access": {},
        "restricted_fields": [],
        "employees": 0,
        "created_by": 7,
        "updated_by": 7,
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


class CrmRoles:
    """`/api/v1/platform-roles*` CRM в памяти: системные неизменны, занятая роль не удаляется."""

    def __init__(self, be: Backends) -> None:
        self.roles: dict[int, dict[str, Any]] = {
            1: crm_role(
                1,
                "Администратор",
                code="ADMIN",
                is_system=True,
                access={"admin": "full", "dashboard.queue": "full"},
                employees=1,
            ),
            2: crm_role(
                2,
                "Директор",
                code="DIRECTOR",
                is_system=True,
                access={"admin": "read", "crm.leads": "full"},
                restricted_fields=["cost_margin", "supplier_prices"],
            ),
            3: crm_role(
                3, "Менеджер", code="tpl:MANAGER", access={"crm.leads": "full"}, employees=2
            ),
        }
        self.next_id = 40
        self.preview_body: dict[str, Any] = {}
        router = be.router
        self.list_route = router.get(ROLES).mock(side_effect=self._list)
        self.create_route = router.post(ROLES).mock(side_effect=self._create)
        self.preview_route = router.post(f"{ROLES}/preview").mock(side_effect=self._preview)
        one = rf"{ROLES}/\d+$"
        self.get_route = router.get(url__regex=one).mock(side_effect=self._get)
        self.patch_route = router.patch(url__regex=one).mock(side_effect=self._patch)
        self.delete_route = router.delete(url__regex=one).mock(side_effect=self._delete)

    @staticmethod
    def _error(status: int, code: str, **details: Any) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": code, "details": details})

    @staticmethod
    def _id(request: httpx.Request) -> int:
        return int(request.url.path.rsplit("/", 1)[1])

    def _list(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=list(self.roles.values()))

    def _get(self, request: httpx.Request) -> httpx.Response:
        role = self.roles.get(self._id(request))
        return httpx.Response(200, json=role) if role else self._error(404, "not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if any(r["name"].lower() == body["name"].lower() for r in self.roles.values()):
            return self._error(409, "conflict", field="name")
        if "payroll" in body.get("access", {}):
            return self._error(422, "validation_failed", field="access")
        self.next_id += 1
        role = crm_role(self.next_id, **body)
        self.roles[self.next_id] = role
        return httpx.Response(201, json=role)

    def _patch(self, request: httpx.Request) -> httpx.Response:
        role = self.roles.get(self._id(request))
        if role is None:
            return self._error(404, "not_found")
        if role["is_system"]:
            return self._error(409, "role_system")
        role.update(json.loads(request.content))
        return httpx.Response(200, json=role)

    def _delete(self, request: httpx.Request) -> httpx.Response:
        role = self.roles.get(self._id(request))
        if role is None:
            return self._error(404, "not_found")
        if role["is_system"]:
            return self._error(409, "role_system")
        if role["employees"]:
            return self._error(409, "role_in_use", users=role["employees"])
        del self.roles[role["id"]]
        return httpx.Response(204)

    def _preview(self, request: httpx.Request) -> httpx.Response:
        self.preview_body = json.loads(request.content)
        role_id = self.preview_body.get("role_id")
        if role_id is not None and self.roles[role_id]["is_system"]:
            return self._error(409, "role_system")
        employees = (
            [
                {
                    "user_id": 11,
                    "full_name": "Анна Демова",
                    "is_active": True,
                    "gained": [{"resource": "eds.payments", "level": "full"}],
                    "lost": [{"resource": "crm.leads", "level": "full"}],
                    "fields_gained": ["totals_only"],
                    "fields_lost": [],
                    "erp_gained": ["finance.payment"],
                    "erp_lost": [],
                }
            ]
            if role_id
            else []
        )
        return httpx.Response(
            200,
            json={
                "role_id": role_id,
                "employees_total": 2 if role_id else 0,
                "employees": employees,
                "gained": [{"resource": "eds.payments", "level": "full"}] if role_id else [],
                "lost": [{"resource": "crm.leads", "level": "full"}] if role_id else [],
                "fields_gained": ["totals_only"] if role_id else [],
                "fields_lost": [],
            },
        )


@pytest.fixture
def roles(be: Backends) -> CrmRoles:
    return CrmRoles(be)


# --- список, чтение, доступ --------------------------------------------------------------------


async def test_list_roles_maps_crm_roles(web: Web, roles: CrmRoles, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get("/api/v1/admin/roles")

    assert response.status_code == 200
    check(response, "/admin/roles", "get")
    items = response.json()["items"]
    assert [(r["id"], r["name"], r["system"]) for r in items] == [
        ("1", "Администратор", True),
        ("2", "Директор", True),
        ("3", "Менеджер", False),
    ]
    assert items[1]["restricted_fields"] == ["cost_margin", "supplier_prices"]
    assert items[2]["employees"] == 2
    assert items[2]["code"] == "tpl:MANAGER"
    assert "created_by" not in response.text


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "ACCOUNTANT"])
async def test_only_admin_full_manages_roles(
    web: Web, roles: CrmRoles, check: ContractChecker, role: str
) -> None:
    """Раздел `admin` полный — только у ролей с ним (директор — чтение: матрицы не видит)."""
    await web.login([role])

    for method, url, body in (
        ("GET", "/api/v1/admin/roles", None),
        ("GET", "/api/v1/admin/roles/3", None),
        ("POST", "/api/v1/admin/roles", {"name": "Х", "access": {}, "restricted_fields": []}),
        ("PATCH", "/api/v1/admin/roles/3", {"name": "Х"}),
        ("DELETE", "/api/v1/admin/roles/3", None),
        ("POST", "/api/v1/admin/roles/preview", {}),
    ):
        if method == "GET":
            response = await web.client.get(url)
        else:
            response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert roles.list_route.call_count == roles.create_route.call_count == 0


async def test_get_role_and_unknown_role(web: Web, roles: CrmRoles, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    one = await web.client.get("/api/v1/admin/roles/3")
    missing = await web.client.get("/api/v1/admin/roles/999")
    bad = await web.client.get("/api/v1/admin/roles/abc")

    check(one, "/admin/roles/{id}", "get")
    assert one.json()["access"] == {"crm.leads": "full"}
    assert missing.status_code == 404
    check(missing, "/admin/roles/{id}", "get")
    assert bad.status_code == 422
    assert roles.get_route.call_count == 2


# --- создание, переименование, удаление ---------------------------------------------------------

MIXED = {
    "name": " Менеджер и бухгалтер ",
    "description": "Маленькая компания: продажи и деньги",
    "access": {"crm.leads": "full", "eds.payments": "full"},
    "restricted_fields": ["totals_only"],
}


async def test_create_role_goes_to_crm_as_is(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/roles", json=MIXED)

    assert response.status_code == 201
    check(response, "/admin/roles", "post")
    created = response.json()
    assert created["name"] == "Менеджер и бухгалтер"
    assert created["system"] is False
    assert "code" not in created
    assert json.loads(roles.create_route.calls.last.request.content) == {
        "name": "Менеджер и бухгалтер",
        "description": "Маленькая компания: продажи и деньги",
        "access": {"crm.leads": "full", "eds.payments": "full"},
        "restricted_fields": ["totals_only"],
    }


async def test_create_role_name_taken_and_unknown_section(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    taken = await web.send("POST", "/api/v1/admin/roles", json={**MIXED, "name": "менеджер"})
    unknown = await web.send(
        "POST", "/api/v1/admin/roles", json={**MIXED, "access": {"payroll": "full"}}
    )

    assert taken.status_code == 409
    check(taken, "/admin/roles", "post")
    assert taken.json()["code"] == "CONFLICT"
    assert taken.json()["details"]["reason"] == "name_taken"
    assert "названием" in taken.json()["message"]
    assert unknown.status_code == 422
    check(unknown, "/admin/roles", "post")
    assert unknown.json()["details"]["fields"] == ["access"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Х"},
        {"name": "  ", "access": {}, "restricted_fields": []},
        {"name": "Х", "access": {"crm.leads": "hidden"}, "restricted_fields": []},
        {"name": "Х", "access": {}, "restricted_fields": ["salary"]},
        {"name": "Х", "access": {}, "restricted_fields": [], "code": "ADMIN"},
    ],
)
async def test_create_role_body_is_validated(
    web: Web, roles: CrmRoles, payload: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/roles", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert roles.create_route.call_count == 0


async def test_rename_role_sends_only_the_changed_fields(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("PATCH", "/api/v1/admin/roles/3", json={"name": " Продажи "})

    assert response.status_code == 200
    check(response, "/admin/roles/{id}", "patch")
    assert response.json()["name"] == "Продажи"
    assert json.loads(roles.patch_route.calls.last.request.content) == {"name": "Продажи"}


async def test_system_roles_are_not_editable(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    patch = await web.send("PATCH", "/api/v1/admin/roles/2", json={"access": {}})
    delete = await web.send("DELETE", "/api/v1/admin/roles/1")
    preview = await web.send("POST", "/api/v1/admin/roles/preview", json={"role_id": "2"})

    for response, path, method in (
        (patch, "/admin/roles/{id}", "patch"),
        (delete, "/admin/roles/{id}", "delete"),
        (preview, "/admin/roles/preview", "post"),
    ):
        assert response.status_code == 409
        check(response, path, method)
        assert response.json()["code"] == "ROLE_SYSTEM"
        assert response.json()["message"] == "Системную роль нельзя изменить или удалить."


async def test_role_with_employees_is_not_deleted(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("DELETE", "/api/v1/admin/roles/3")

    assert response.status_code == 409
    check(response, "/admin/roles/{id}", "delete")
    body = response.json()
    assert body["code"] == "ROLE_IN_USE"
    assert body["details"]["employees"] == 2
    assert body["details"]["reason"] == "role_in_use"
    assert "сотрудникам (2)" in body["message"]
    assert 3 in roles.roles


async def test_free_role_is_deleted(web: Web, roles: CrmRoles, check: ContractChecker) -> None:
    await web.login(["ADMIN"])
    created = (await web.send("POST", "/api/v1/admin/roles", json=MIXED)).json()

    response = await web.send("DELETE", f"/api/v1/admin/roles/{created['id']}")

    assert response.status_code == 204
    check(response, "/admin/roles/{id}", "delete")
    assert int(created["id"]) not in roles.roles


async def test_editing_own_role_expires_the_profile_cache(web: Web, roles: CrmRoles) -> None:
    await web.login(["ADMIN", "MANAGER"])
    calls = web.be.crm_me.call_count

    await web.send("PATCH", "/api/v1/admin/roles/3", json={"name": "Продажи"})
    await web.client.get("/api/v1/me")

    assert web.be.crm_me.call_count == calls + 1


# --- «Что произойдёт» -----------------------------------------------------------------------------


async def test_preview_maps_employees_and_sections(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    draft = {
        "role_id": "3",
        "access": {"eds.payments": "full"},
        "restricted_fields": ["totals_only"],
    }

    response = await web.send("POST", "/api/v1/admin/roles/preview", json=draft)

    assert response.status_code == 200
    check(response, "/admin/roles/preview", "post")
    body = response.json()
    assert roles.preview_body == {**draft, "role_id": 3}
    assert body["role_id"] == "3"
    assert body["employees_total"] == 2
    assert body["employees"] == [
        {
            "employee": {"id": "11", "name": "Анна Демова", "initials": "АД"},
            "gained": [{"resource": "eds.payments", "level": "full"}],
            "lost": [{"resource": "crm.leads", "level": "full"}],
            "fields_gained": ["totals_only"],
            "fields_lost": [],
        }
    ]
    assert "erp_gained" not in response.text  # права бэкенда наружу не уходят


async def test_preview_of_a_new_role_touches_nobody(
    web: Web, roles: CrmRoles, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "POST", "/api/v1/admin/roles/preview", json={"access": {"crm.leads": "full"}}
    )

    check(response, "/admin/roles/preview", "post")
    assert response.json()["role_id"] is None
    assert response.json()["employees_total"] == 0
    assert roles.preview_body == {"access": {"crm.leads": "full"}}


# --- повтор приглашения -------------------------------------------------------------------------


@pytest.fixture
def crm(be: Backends) -> CrmUsers:
    fake = CrmUsers(be)
    fake.users = {12: crm_user(12, "Борис Приглашённый", must_change_password=True)}
    return fake


async def test_resend_invite(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", "/api/v1/admin/users/12/invite")

    assert response.status_code == 200
    check(response, "/admin/users/{id}/invite", "post")
    assert response.json()["status"] == "invited"
    assert crm.invite_route.calls.last.request.url.path == "/api/v1/users/12/invite"
    assert crm.create_route.call_count == 0


async def test_resend_invite_without_mail_is_not_sent(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.invite_response = CrmUsers._error(409, "conflict", reason="smtp_not_configured")

    response = await web.send("POST", "/api/v1/admin/users/12/invite")

    assert response.status_code == 409
    check(response, "/admin/users/{id}/invite", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["invite"] == "not_sent"
    assert response.json()["details"]["employee_id"] == "12"


async def test_resend_invite_crm_down_and_rights(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.invite_route.mock(side_effect=httpx.ConnectError("down"))

    down = await web.send("POST", "/api/v1/admin/users/12/invite")

    assert down.status_code == 503
    check(down, "/admin/users/{id}/invite", "post")
    assert "Письмо не отправлено" in down.json()["message"]
    web.client.cookies.clear()
    await web.login(["DIRECTOR"])
    assert (await web.send("POST", "/api/v1/admin/users/12/invite")).status_code == 403


async def test_new_mutations_need_csrf(
    web: Web, roles: CrmRoles, crm: CrmUsers, check: ContractChecker
) -> None:
    """Изменяющие операции 0.3.0 без верного `X-CSRF-Token` — 403 `CSRF_FAILED`, в CRM не уходят."""
    await web.login(["ADMIN"])
    body = {"name": "Х", "access": {}, "restricted_fields": []}

    for method, url, payload, path in (
        ("POST", "/api/v1/admin/roles", body, "/admin/roles"),
        ("PATCH", "/api/v1/admin/roles/3", {"name": "Х"}, "/admin/roles/{id}"),
        ("DELETE", "/api/v1/admin/roles/3", None, "/admin/roles/{id}"),
        ("POST", "/api/v1/admin/roles/preview", {"role_id": "3"}, "/admin/roles/preview"),
        ("POST", "/api/v1/admin/users/12/invite", None, "/admin/users/{id}/invite"),
    ):
        response = await web.send(method, url, json=payload, csrf="x")  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        check(response, path, method.lower())
        assert response.json()["code"] == "CSRF_FAILED"
    assert roles.create_route.call_count == roles.patch_route.call_count == 0
    assert roles.delete_route.call_count == roles.preview_route.call_count == 0
    assert crm.invite_route.call_count == 0
