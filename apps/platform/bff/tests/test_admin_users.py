"""Admin · Оргструктура (PLT-15): список, карточка, выдача ролей, отключение, приглашение.

CRM — на respx с состоянием пользователей; ответы BFF проверяются по схемам platform-bff.yaml.
Решения (последний администратор, роли ERP, письма) за CRM: здесь проверяется перевод в контракт.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.roles import NAMES, ROLE_IDS, ref, rid

ADMIN_ID = 7  # сотрудник из `profile()` — тот, кто входит
CODES = {v: k for k, v in ROLE_IDS.items()}
ADMIN = ROLE_IDS["ADMIN"]


def short_ref(role_id: int) -> dict[str, Any]:
    """Роль в `/users` CRM: без матрицы (матрицы — только в `/me`)."""
    if role_id not in CODES:  # созданная администратором роль без кода
        return {"id": role_id, "name": f"Роль {role_id}", "system": False, "code": None}
    full = ref(CODES[role_id])
    return {k: full[k] for k in ("id", "name", "system", "code")}


def with_refs(user: dict[str, Any]) -> dict[str, Any]:
    return {**user, "platform_role_refs": [short_ref(i) for i in user["platform_role_ids"]]}


def names(employee: dict[str, Any]) -> list[str]:
    return [r["name"] for r in employee["roles"]]


def crm_user(
    user_id: int, name: str, roles: tuple[str, ...] = ("MANAGER",), **extra: Any
) -> dict[str, Any]:
    local = name.split()[0].lower()
    return {
        "id": user_id,
        "email": f"{local}{user_id}@demo.example",
        "full_name": name,
        "roles": ["viewer"],
        "is_active": True,
        "tg_user_id": None,
        "must_change_password": False,
        "ui_mode": "manager",
        "notify_system": True,
        "notify_leads": True,
        "platform_access": ["crm", "erp"],
        "erp_role_codes": [],
        "platform_role_ids": [ROLE_IDS[c] for c in roles],
        "erp_sync": "ok",
        "erp_sync_error": None,
        "position": "Менеджер по продажам",
        "language": "ru",
        **extra,
    }


class CrmUsers:
    """`/api/v1/users*` CRM: пользователи в памяти и инвариант «≥ 1 активный админ» (как в CRM)."""

    def __init__(self, be: Backends) -> None:
        self.users: dict[int, dict[str, Any]] = {}
        self.next_id = 100
        self.invite_response = httpx.Response(
            200, json={"email_log_id": 1, "to_email": "x@demo.example", "status": "queued"}
        )
        self.create_error: httpx.Response | None = None
        self.update_error: httpx.Response | None = None
        self.down = False
        self.forbidden = False
        router = be.router
        self.list_route = router.get(f"{CRM_URL}/api/v1/users").mock(side_effect=self._list)
        self.create_route = router.post(f"{CRM_URL}/api/v1/users").mock(side_effect=self._create)
        self.get_route = router.get(url__regex=rf"{CRM_URL}/api/v1/users/\d+$").mock(
            side_effect=self._get
        )
        self.patch_route = router.patch(url__regex=rf"{CRM_URL}/api/v1/users/\d+$").mock(
            side_effect=self._patch
        )
        self.invite_route = router.post(url__regex=rf"{CRM_URL}/api/v1/users/\d+/invite$").mock(
            side_effect=lambda request: self.invite_response
        )

    @staticmethod
    def _error(status: int, code: str, **details: Any) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": code, "details": details})

    def _common(self) -> httpx.Response | None:
        if self.down:
            raise httpx.ConnectError("crm down")
        if self.forbidden:
            return self._error(403, "forbidden")
        return None

    def _list(self, request: httpx.Request) -> httpx.Response:
        return self._common() or httpx.Response(
            200, json=[with_refs(u) for u in self.users.values()]
        )

    @staticmethod
    def _id(request: httpx.Request) -> int:
        return int(request.url.path.split("/")[4])

    def _get(self, request: httpx.Request) -> httpx.Response:
        if (early := self._common()) is not None:
            return early
        user = self.users.get(self._id(request))
        return httpx.Response(200, json=with_refs(user)) if user else self._error(404, "not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        if (early := self._common()) is not None:
            return early
        if self.create_error is not None:
            return self.create_error
        body = json.loads(request.content)
        self.next_id += 1
        user = crm_user(
            self.next_id,
            body["full_name"],
            tuple(CODES[i] for i in body["platform_role_ids"]),
            email=body["email"],
            position=body.get("position"),
            must_change_password=True,
            erp_sync="pending",
        )
        self.users[self.next_id] = user
        return httpx.Response(
            201, json={"user": with_refs(user), "temporary_password": "Tmp-secret-1"}
        )

    def _active_admins(self, excluding: int) -> int:
        return sum(
            1
            for u in self.users.values()
            if u["id"] != excluding and u["is_active"] and ADMIN in u["platform_role_ids"]
        )

    def _patch(self, request: httpx.Request) -> httpx.Response:
        if (early := self._common()) is not None:
            return early
        if self.update_error is not None:
            return self.update_error
        user = self.users.get(user_id := self._id(request))
        if user is None:
            return self._error(404, "not_found")
        body = json.loads(request.content)
        was_admin = ADMIN in user["platform_role_ids"]
        loses = was_admin and (
            ("platform_role_ids" in body and ADMIN not in body["platform_role_ids"])
            or body.get("is_active") is False
        )
        if loses and self._active_admins(user_id) == 0:
            return self._error(409, "last_admin")
        user.update({k: v for k, v in body.items() if k in user})
        return httpx.Response(200, json=with_refs(user))


@pytest.fixture
def crm(be: Backends) -> CrmUsers:
    fake = CrmUsers(be)
    fake.users = {
        ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", ("ADMIN",), position="Админ"),
        11: crm_user(11, "Анна Демова", ("SUPPLY", "MANAGER")),
        12: crm_user(
            12,
            "Борис Приглашённый",
            ("ACCOUNTANT",),
            must_change_password=True,
            platform_access=["crm"],
            position=None,
            erp_sync="not_applicable",
        ),
        13: crm_user(13, "Виктор Отключённый", is_active=False, tg_user_id=123456),
    }
    return fake


async def login_as(web: Web, role: str) -> None:
    await web.login([role])


# --- список и карточка ---


async def test_list_maps_crm_users_to_employees(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.client.get("/api/v1/admin/users")

    assert response.status_code == 200
    check(response, "/admin/users", "get")
    items = {e["id"]: e for e in response.json()["items"]}
    assert [e["name"] for e in response.json()["items"]] == [
        "Анна Демова",
        "Борис Приглашённый",
        "Виктор Отключённый",
        "Иван Тестов",
    ]
    anna = items["11"]
    # Роли — данные CRM: id, название, системная ли, код; порядок CRM.
    assert anna["roles"] == [
        {"id": rid("SUPPLY"), "name": "Снабженец", "system": False, "code": "tpl:SUPPLY"},
        {"id": rid("MANAGER"), "name": "Менеджер", "system": False, "code": "tpl:MANAGER"},
    ]
    assert anna["position"] == "Менеджер по продажам"
    assert anna["access"] == {"crm": True, "erp": True}
    assert anna["status"] == "active"
    assert anna["telegram_linked"] is False
    assert anna["erp_sync"] == "ok"
    assert anna["initials"] == "АД"
    boris = items["12"]
    assert boris["status"] == "invited"
    assert boris["access"] == {"crm": True, "erp": False}
    assert boris["erp_sync"] == "not_applicable"
    assert "position" not in boris  # пустая должность не выдумывается
    assert items["13"]["status"] == "disabled"
    assert items["13"]["telegram_linked"] is True
    sent = crm.list_route.calls.last.request
    assert sent.headers["authorization"].startswith("Bearer crm-access-")


async def test_list_never_leaks_crm_internals(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")

    body = (await web.client.get("/api/v1/admin/users")).text

    for forbidden in ("password", "tg_user_id", "erp_role_codes", "ui_mode", "notify_"):
        assert forbidden not in body


async def test_list_filters_by_query_and_status(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")

    by_name = (await web.client.get("/api/v1/admin/users", params={"q": "  АННА "})).json()
    by_email = (await web.client.get("/api/v1/admin/users", params={"q": "борис12@"})).json()
    disabled = (await web.client.get("/api/v1/admin/users", params={"status": "disabled"})).json()
    invited = (
        await web.client.get("/api/v1/admin/users", params={"status": "invited", "q": "борис"})
    ).json()

    assert [e["id"] for e in by_name["items"]] == ["11"]
    assert [e["id"] for e in by_email["items"]] == ["12"]
    assert [e["id"] for e in disabled["items"]] == ["13"]
    assert [e["id"] for e in invited["items"]] == ["12"]


async def test_list_rejects_unknown_status(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")

    response = await web.client.get("/api/v1/admin/users", params={"status": "fired"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == ["query.status"]


async def test_get_employee(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")

    response = await web.client.get("/api/v1/admin/users/11")

    assert response.status_code == 200
    check(response, "/admin/users/{id}", "get")
    assert response.json()["email"] == "анна11@demo.example"
    assert names(response.json()) == ["Снабженец", "Менеджер"]


async def test_erp_sync_comes_from_crm(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    """Итог провижининга ERP — из CRM (`erp_sync`, `erp_sync_error`), BFF его не выдумывает."""
    await login_as(web, "ADMIN")
    crm.users[11].update(erp_sync="error", erp_sync_error="ERP: нет связи")

    response = await web.client.get("/api/v1/admin/users/11")

    check(response, "/admin/users/{id}", "get")
    assert response.json()["erp_sync"] == "error"
    assert response.json()["erp_sync_error"] == "ERP: нет связи"


async def test_get_unknown_employee_is_404(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")

    response = await web.client.get("/api/v1/admin/users/999")

    assert response.status_code == 404
    check(response, "/admin/users/{id}", "get")
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["source"] == "crm"


async def test_get_employee_id_must_be_numeric(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")

    response = await web.client.get("/api/v1/admin/users/abc")

    assert response.status_code == 422
    assert crm.get_route.call_count == 0


# --- доступ по матрице (раздел admin: ADMIN — full, DIRECTOR — read) ---


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_roles_without_admin_section_get_403(
    web: Web, crm: CrmUsers, check: ContractChecker, role: str
) -> None:
    await login_as(web, role)

    listing = await web.client.get("/api/v1/admin/users")
    card = await web.client.get("/api/v1/admin/users/11")
    patch = await web.send("PATCH", "/api/v1/admin/users/11", json={"role_ids": [rid("ADMIN")]})
    invite = await web.send(
        "POST",
        "/api/v1/admin/users/invite",
        json={"email": "new@demo.example", "name": "Новый", "role_ids": [rid("MANAGER")]},
    )

    for response, path, method in (
        (listing, "/admin/users", "get"),
        (card, "/admin/users/{id}", "get"),
        (patch, "/admin/users/{id}", "patch"),
        (invite, "/admin/users/invite", "post"),
    ):
        assert response.status_code == 403
        check(response, path, method)
        assert response.json()["code"] == "FORBIDDEN"
        assert response.json()["source"] == "bff"
    assert (
        crm.list_route.call_count == crm.patch_route.call_count == crm.create_route.call_count == 0
    )


async def test_director_reads_but_cannot_change(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "DIRECTOR")

    listing = await web.client.get("/api/v1/admin/users")
    card = await web.client.get("/api/v1/admin/users/11")
    patch = await web.send("PATCH", "/api/v1/admin/users/11", json={"is_active": False})
    invite = await web.send(
        "POST",
        "/api/v1/admin/users/invite",
        json={"email": "new@demo.example", "name": "Новый", "role_ids": [rid("MANAGER")]},
    )

    assert listing.status_code == 200
    check(listing, "/admin/users", "get")
    assert card.status_code == 200
    assert patch.status_code == invite.status_code == 403
    check(patch, "/admin/users/{id}", "patch")
    check(invite, "/admin/users/invite", "post")
    assert patch.json()["details"] == {"resource": "admin", "need": "full"}
    assert crm.patch_route.call_count == crm.create_route.call_count == 0


async def test_crm_refusal_for_a_reader_is_forbidden_from_crm(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    """Базовая роль CRM у директора — `viewer`: если CRM закрыла `users:read`, это 403 от crm."""
    await login_as(web, "DIRECTOR")
    crm.forbidden = True

    response = await web.client.get("/api/v1/admin/users")

    assert response.status_code == 403
    check(response, "/admin/users", "get")
    assert response.json()["source"] == "crm"
    assert response.json()["details"]["backend_status"] == 403


async def test_requires_session(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    response = await web.client.get("/api/v1/admin/users")

    assert response.status_code == 401
    check(response, "/admin/users", "get")


# --- выдача ролей, должность, отключение ---


async def test_assign_several_roles(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")

    response = await web.send(
        "PATCH", "/api/v1/admin/users/12", json={"role_ids": [rid("SUPPLY"), rid("ENGINEER")]}
    )

    assert response.status_code == 200
    check(response, "/admin/users/{id}", "patch")
    assert names(response.json()) == ["Снабженец", "Гл. инженер"]
    sent = json.loads(crm.patch_route.calls.last.request.content)
    # Полный набор id; BFF не вычисляет права и не пишет роли кодами (роли без кода не слетят).
    assert sent == {"platform_role_ids": [ROLE_IDS["SUPPLY"], ROLE_IDS["ENGINEER"]]}
    assert crm.patch_route.calls.last.request.url.path == "/api/v1/users/12"
    assert crm.get_route.call_count == 0  # без чтения «до»: никакого read-modify-write
    again = (await web.client.get("/api/v1/admin/users/12")).json()
    assert names(again) == ["Снабженец", "Гл. инженер"]


async def test_created_role_without_code_is_kept_when_roles_change(web: Web, crm: CrmUsers) -> None:
    """Роль без кода (создана администратором) уходит в CRM тем же id, а не теряется."""
    await login_as(web, "ADMIN")

    response = await web.send(
        "PATCH", "/api/v1/admin/users/11", json={"role_ids": ["40", rid("MANAGER")]}
    )

    assert json.loads(crm.patch_route.calls.last.request.content) == {
        "platform_role_ids": [40, ROLE_IDS["MANAGER"]]
    }
    assert response.status_code == 200


async def test_position_is_trimmed_and_can_be_cleared(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    changed = await web.send(
        "PATCH", "/api/v1/admin/users/11", json={"position": "  Старший менеджер "}
    )
    cleared = await web.send("PATCH", "/api/v1/admin/users/11", json={"position": ""})

    assert changed.json()["position"] == "Старший менеджер"
    assert json.loads(crm.patch_route.calls[0].request.content) == {"position": "Старший менеджер"}
    check(cleared, "/admin/users/{id}", "patch")
    assert json.loads(crm.patch_route.calls[1].request.content) == {"position": ""}
    assert "position" not in cleared.json()


async def test_disable_and_enable(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")

    off = await web.send("PATCH", "/api/v1/admin/users/11", json={"is_active": False})
    on = await web.send("PATCH", "/api/v1/admin/users/11", json={"is_active": True})

    assert off.json()["status"] == "disabled"
    assert on.json()["status"] == "active"
    check(off, "/admin/users/{id}", "patch")
    assert json.loads(crm.patch_route.calls[0].request.content) == {"is_active": False}


async def test_removing_all_roles_is_passed_to_crm(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("PATCH", "/api/v1/admin/users/11", json={"role_ids": []})

    assert response.status_code == 200
    assert json.loads(crm.patch_route.calls.last.request.content) == {"platform_role_ids": []}
    assert response.json()["roles"] == []


async def test_admin_can_drop_own_admin_role_when_another_admin_exists(
    web: Web, crm: CrmUsers
) -> None:
    await login_as(web, "ADMIN")
    crm.users[11]["platform_role_ids"] = [ADMIN]

    response = await web.send(
        "PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"role_ids": [rid("MANAGER")]}
    )

    assert response.status_code == 200
    assert names(response.json()) == ["Менеджер"]


async def test_last_admin_cannot_drop_own_admin_role(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send(
        "PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"role_ids": [rid("MANAGER")]}
    )

    assert response.status_code == 409
    check(response, "/admin/users/{id}", "patch")
    body = response.json()
    assert body["code"] == "LAST_ADMIN"
    assert body["source"] == "crm"
    assert "последнего администратора" in body["message"]
    assert body["details"]["backend_code"] == "last_admin"
    assert body["details"]["reason"] == "last_admin"
    assert crm.users[ADMIN_ID]["platform_role_ids"] == [ADMIN]  # CRM ничего не записал


async def test_last_admin_cannot_be_disabled(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"is_active": False})

    assert response.status_code == 409
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["code"] == "LAST_ADMIN"


async def test_active_leads_block_is_a_readable_conflict(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")
    crm.update_error = CrmUsers._error(409, "user_has_active_leads", count=3)

    response = await web.send("PATCH", "/api/v1/admin/users/11", json={"is_active": False})

    assert response.status_code == 409
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["code"] == "CONFLICT"
    assert "лиды" in response.json()["message"]
    assert response.json()["details"]["backend_code"] == "user_has_active_leads"
    assert response.json()["details"]["reason"] == "user_has_active_leads"


async def test_transfer_of_leads_goes_to_crm(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    """Отключение с передачей лидов коллеге: `transfer_to_user_id` уходит в CRM числом."""
    await login_as(web, "ADMIN")

    response = await web.send(
        "PATCH",
        "/api/v1/admin/users/11",
        json={"is_active": False, "transfer_to_user_id": str(ADMIN_ID)},
    )

    assert response.status_code == 200
    check(response, "/admin/users/{id}", "patch")
    assert json.loads(crm.patch_route.calls.last.request.content) == {
        "is_active": False,
        "transfer_to_user_id": ADMIN_ID,
    }


async def test_last_director_is_a_named_conflict(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")
    crm.update_error = CrmUsers._error(409, "last_director")

    response = await web.send("PATCH", "/api/v1/admin/users/11", json={"role_ids": []})

    assert response.status_code == 409
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["code"] == "LAST_DIRECTOR"
    assert "последнего директора" in response.json()["message"]


async def test_crm_validation_error_lists_fields(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")
    crm.update_error = CrmUsers._error(
        422, "validation_failed", field="platform_role_ids", errors=[{"field": "platform_role_ids"}]
    )

    response = await web.send(
        "PATCH", "/api/v1/admin/users/11", json={"role_ids": [rid("MANAGER")]}
    )

    assert response.status_code == 422
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["details"]["fields"] == ["role_ids"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role_ids": ["BOSS"]},
        {"role_ids": ["3", "3"]},
        {"role_ids": None},
        {"roles": ["3"]},
        {"position": "я" * 121},
        {"is_active": None},
        {"transfer_to_user_id": "x"},
        {"full_name": "Другое Имя"},
    ],
)
async def test_update_body_is_validated(web: Web, crm: CrmUsers, payload: dict[str, Any]) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("PATCH", "/api/v1/admin/users/11", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.patch_route.call_count == 0


async def test_update_unknown_employee_is_404(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("PATCH", "/api/v1/admin/users/999", json={"is_active": False})

    assert response.status_code == 404
    check(response, "/admin/users/{id}", "patch")


async def test_mutations_need_csrf(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")

    patch = await web.send("PATCH", "/api/v1/admin/users/11", json={"is_active": False}, csrf="x")
    invite = await web.send(
        "POST",
        "/api/v1/admin/users/invite",
        json={"email": "n@demo.example", "name": "Н", "role_ids": [rid("MANAGER")]},
        csrf="x",
    )

    assert patch.status_code == invite.status_code == 403
    assert patch.json()["code"] == invite.json()["code"] == "CSRF_FAILED"
    assert crm.patch_route.call_count == crm.create_route.call_count == 0


async def test_crm_unavailable_is_503(web: Web, crm: CrmUsers, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")
    crm.down = True

    response = await web.client.get("/api/v1/admin/users")

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "crm"


# --- приглашение ---


INVITE = {
    "email": "new.employee@demo.example",
    "name": "  Новый Сотрудник ",
    "position": " Инженер ",
    "role_ids": [rid("ENGINEER"), rid("SUPPLY")],
}


async def test_invite_creates_user_and_sends_mail(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/invite", json=INVITE)

    assert response.status_code == 201
    check(response, "/admin/users/invite", "post")
    created = response.json()
    assert created["name"] == "Новый Сотрудник"
    assert names(created) == ["Гл. инженер", "Снабженец"]
    assert created["status"] == "invited"
    assert created["access"] == {"crm": True, "erp": True}
    assert created["erp_sync"] == "pending"
    assert json.loads(crm.create_route.calls.last.request.content) == {
        "email": "new.employee@demo.example",
        "full_name": "Новый Сотрудник",
        "platform_role_ids": [ROLE_IDS["ENGINEER"], ROLE_IDS["SUPPLY"]],
        "position": "Инженер",
    }
    assert crm.invite_route.calls.last.request.url.path == f"/api/v1/users/{created['id']}/invite"
    assert "Tmp-secret-1" not in response.text  # временный пароль в браузер не уходит
    assert "password" not in response.text


async def test_invite_without_position(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")
    payload = {"email": "n@demo.example", "name": "Новый", "role_ids": [rid("DIRECTOR")]}

    response = await web.send("POST", "/api/v1/admin/users/invite", json=payload)

    assert response.status_code == 201
    assert "position" not in json.loads(crm.create_route.calls.last.request.content)


async def test_invite_existing_email_is_409_email_exists(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")
    crm.create_error = CrmUsers._error(409, "conflict", reason="email_taken", field="email")

    response = await web.send("POST", "/api/v1/admin/users/invite", json=INVITE)

    assert response.status_code == 409
    check(response, "/admin/users/invite", "post")
    assert response.json()["code"] == "EMAIL_EXISTS"
    assert response.json()["source"] == "crm"
    assert crm.invite_route.call_count == 0


async def test_invite_when_mail_is_not_configured(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    """Пользователь создан, письмо не ушло: ошибка несёт id, пароль не раскрывается."""
    await login_as(web, "ADMIN")
    crm.invite_response = CrmUsers._error(409, "conflict", reason="smtp_not_configured")

    response = await web.send("POST", "/api/v1/admin/users/invite", json=INVITE)

    assert response.status_code == 409
    check(response, "/admin/users/invite", "post")
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert "письмо не отправлено" in body["message"]
    assert body["details"]["employee_id"] == "101"
    assert body["details"]["invite"] == "not_sent"
    assert "Tmp-secret-1" not in response.text
    assert crm.users[101]["email"] == "new.employee@demo.example"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "n@demo.example", "name": "Новый", "role_ids": []},
        {"email": "n@demo.example", "name": "Новый"},
        {"email": "not-an-email", "name": "Новый", "role_ids": ["3"]},
        {"email": "n@demo.example", "name": "   ", "role_ids": ["3"]},
        {"email": "n@demo.example", "name": "Новый", "role_ids": ["3", "3"]},
        {"email": "n@demo.example", "name": "Новый", "role_ids": ["CEO"]},
        {"email": "n@demo.example", "name": "Новый", "roles": ["MANAGER"]},
        {"email": "n@demo.example", "name": "Новый", "role_ids": ["3"], "password": "x"},
    ],
)
async def test_invite_body_is_validated(web: Web, crm: CrmUsers, payload: dict[str, Any]) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/invite", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.create_route.call_count == 0


async def test_changing_own_roles_expires_the_profile_cache(web: Web) -> None:
    """Свои роли изменены — следующий `/me` сразу идёт в CRM, а не ждёт 60 секунд кэша."""
    be = web.be
    fake = CrmUsers(be)
    fake.users = {ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", ("ADMIN", "MANAGER"))}
    await login_as(web, "ADMIN")
    be.set_roles(["ADMIN", "MANAGER"])
    calls = be.crm_me.call_count

    await web.client.get("/api/v1/me")
    assert be.crm_me.call_count == calls  # кэш жив

    response = await web.send(
        "PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"role_ids": [rid("ADMIN")]}
    )
    be.set_roles(["ADMIN"])
    me = (await web.client.get("/api/v1/me")).json()

    assert response.status_code == 200
    assert be.crm_me.call_count == calls + 1  # профиль перечитан сразу
    assert [r["name"] for r in me["roles"]] == [NAMES["ADMIN"]]


async def test_changing_someone_elses_roles_keeps_the_profile_cache(
    web: Web, crm: CrmUsers
) -> None:
    await login_as(web, "ADMIN")
    calls = web.be.crm_me.call_count

    await web.send("PATCH", "/api/v1/admin/users/11", json={"role_ids": [rid("SUPPLY")]})
    await web.client.get("/api/v1/me")

    assert web.be.crm_me.call_count == calls


async def test_invite_when_crm_goes_down_after_create(web: Web, crm: CrmUsers) -> None:
    """CRM не ответила на приглашение: 503 про CRM, не про почту; id сотрудника в деталях."""
    await login_as(web, "ADMIN")
    crm.invite_route.mock(side_effect=httpx.ConnectError("crm down"))

    response = await web.send("POST", "/api/v1/admin/users/invite", json=INVITE)

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "BACKEND_UNAVAILABLE"
    assert body["source"] == "crm"
    assert "CRM недоступна" in body["message"]
    assert "почт" not in body["message"].lower().replace("отправлено", "")
    assert body["details"]["employee_id"] == "101"
    assert body["details"]["invite"] == "not_sent"
