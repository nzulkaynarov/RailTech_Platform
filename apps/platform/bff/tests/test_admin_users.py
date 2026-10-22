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

ADMIN_ID = 7  # сотрудник из `profile()` — тот, кто входит


def crm_user(user_id: int, name: str, **extra: Any) -> dict[str, Any]:
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
        "platform_roles": ["MANAGER"],
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
        return self._common() or httpx.Response(200, json=list(self.users.values()))

    @staticmethod
    def _id(request: httpx.Request) -> int:
        return int(request.url.path.split("/")[4])

    def _get(self, request: httpx.Request) -> httpx.Response:
        if (early := self._common()) is not None:
            return early
        user = self.users.get(self._id(request))
        return httpx.Response(200, json=user) if user else self._error(404, "not_found")

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
            email=body["email"],
            platform_roles=body["platform_roles"],
            position=body.get("position"),
            must_change_password=True,
        )
        self.users[self.next_id] = user
        return httpx.Response(201, json={"user": user, "temporary_password": "Tmp-secret-1"})

    def _active_admins(self, excluding: int) -> int:
        return sum(
            1
            for u in self.users.values()
            if u["id"] != excluding and u["is_active"] and "ADMIN" in u["platform_roles"]
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
        was_admin = "ADMIN" in user["platform_roles"]
        loses = was_admin and (
            ("platform_roles" in body and "ADMIN" not in body["platform_roles"])
            or body.get("is_active") is False
        )
        if loses and self._active_admins(user_id) == 0:
            return self._error(409, "last_admin")
        user.update({k: v for k, v in body.items() if k in user})
        return httpx.Response(200, json=user)


@pytest.fixture
def crm(be: Backends) -> CrmUsers:
    fake = CrmUsers(be)
    fake.users = {
        ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", platform_roles=["ADMIN"], position="Админ"),
        11: crm_user(11, "Анна Демова", platform_roles=["SUPPLY", "MANAGER"]),
        12: crm_user(
            12,
            "Борис Приглашённый",
            must_change_password=True,
            platform_access=["crm"],
            platform_roles=["ACCOUNTANT"],
            position=None,
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
    assert anna["roles"] == ["MANAGER", "SUPPLY"]  # порядок контракта, не порядок CRM
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
    assert response.json()["roles"] == ["MANAGER", "SUPPLY"]


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
    patch = await web.send("PATCH", "/api/v1/admin/users/11", json={"roles": ["ADMIN"]})
    invite = await web.send(
        "POST",
        "/api/v1/admin/users/invite",
        json={"email": "new@demo.example", "name": "Новый", "roles": ["MANAGER"]},
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
        json={"email": "new@demo.example", "name": "Новый", "roles": ["MANAGER"]},
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
        "PATCH", "/api/v1/admin/users/12", json={"roles": ["SUPPLY", "ENGINEER"]}
    )

    assert response.status_code == 200
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["roles"] == ["SUPPLY", "ENGINEER"]
    sent = json.loads(crm.patch_route.calls.last.request.content)
    assert sent == {"platform_roles": ["SUPPLY", "ENGINEER"]}  # BFF не вычисляет роли CRM и ERP
    assert crm.patch_route.calls.last.request.url.path == "/api/v1/users/12"
    # Следующее чтение видит новые роли: источник истины — CRM.
    again = (await web.client.get("/api/v1/admin/users/12")).json()
    assert again["roles"] == ["SUPPLY", "ENGINEER"]


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

    response = await web.send("PATCH", "/api/v1/admin/users/11", json={"roles": []})

    assert response.status_code == 200
    assert json.loads(crm.patch_route.calls.last.request.content) == {"platform_roles": []}
    assert response.json()["roles"] == []


async def test_admin_can_drop_own_admin_role_when_another_admin_exists(
    web: Web, crm: CrmUsers
) -> None:
    await login_as(web, "ADMIN")
    crm.users[11]["platform_roles"] = ["ADMIN"]

    response = await web.send(
        "PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"roles": ["MANAGER"]}
    )

    assert response.status_code == 200
    assert response.json()["roles"] == ["MANAGER"]


async def test_last_admin_cannot_drop_own_admin_role(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send(
        "PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"roles": ["MANAGER"]}
    )

    assert response.status_code == 409
    check(response, "/admin/users/{id}", "patch")
    body = response.json()
    assert body["code"] == "LAST_ADMIN"
    assert body["source"] == "crm"
    assert "последнего администратора" in body["message"]
    assert body["details"]["backend_code"] == "last_admin"
    assert crm.users[ADMIN_ID]["platform_roles"] == ["ADMIN"]  # CRM ничего не записал


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


async def test_crm_validation_error_lists_fields(
    web: Web, crm: CrmUsers, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")
    crm.update_error = CrmUsers._error(
        422, "validation_failed", field="platform_roles", errors=[{"field": "platform_roles"}]
    )

    response = await web.send("PATCH", "/api/v1/admin/users/11", json={"roles": ["MANAGER"]})

    assert response.status_code == 422
    check(response, "/admin/users/{id}", "patch")
    assert response.json()["details"]["fields"] == ["roles"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"roles": ["BOSS"]},
        {"roles": ["MANAGER", "MANAGER"]},
        {"roles": None},
        {"position": "я" * 121},
        {"is_active": None},
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
        json={"email": "n@demo.example", "name": "Н", "roles": ["MANAGER"]},
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
    "roles": ["ENGINEER", "SUPPLY"],
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
    assert created["roles"] == ["SUPPLY", "ENGINEER"]
    assert created["status"] == "invited"
    assert created["access"] == {"crm": True, "erp": True}
    assert json.loads(crm.create_route.calls.last.request.content) == {
        "email": "new.employee@demo.example",
        "full_name": "Новый Сотрудник",
        "platform_roles": ["ENGINEER", "SUPPLY"],
        "position": "Инженер",
    }
    assert crm.invite_route.calls.last.request.url.path == f"/api/v1/users/{created['id']}/invite"
    assert "Tmp-secret-1" not in response.text  # временный пароль в браузер не уходит
    assert "password" not in response.text


async def test_invite_without_position(web: Web, crm: CrmUsers) -> None:
    await login_as(web, "ADMIN")
    payload = {"email": "n@demo.example", "name": "Новый", "roles": ["DIRECTOR"]}

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
        {"email": "n@demo.example", "name": "Новый", "roles": []},
        {"email": "n@demo.example", "name": "Новый"},
        {"email": "not-an-email", "name": "Новый", "roles": ["MANAGER"]},
        {"email": "n@demo.example", "name": "   ", "roles": ["MANAGER"]},
        {"email": "n@demo.example", "name": "Новый", "roles": ["MANAGER", "MANAGER"]},
        {"email": "n@demo.example", "name": "Новый", "roles": ["CEO"]},
        {"email": "n@demo.example", "name": "Новый", "roles": ["MANAGER"], "password": "x"},
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
    fake.users = {ADMIN_ID: crm_user(ADMIN_ID, "Иван Тестов", platform_roles=["ADMIN", "MANAGER"])}
    await login_as(web, "ADMIN")
    be.profile["platform_roles"] = ["ADMIN", "MANAGER"]
    calls = be.crm_me.call_count

    await web.client.get("/api/v1/me")
    assert be.crm_me.call_count == calls  # кэш жив

    response = await web.send("PATCH", f"/api/v1/admin/users/{ADMIN_ID}", json={"roles": ["ADMIN"]})
    be.profile["platform_roles"] = ["ADMIN"]
    me = (await web.client.get("/api/v1/me")).json()

    assert response.status_code == 200
    assert be.crm_me.call_count == calls + 1  # профиль перечитан сразу
    assert me["roles"] == ["ADMIN"]


async def test_changing_someone_elses_roles_keeps_the_profile_cache(
    web: Web, crm: CrmUsers
) -> None:
    await login_as(web, "ADMIN")
    calls = web.be.crm_me.call_count

    await web.send("PATCH", "/api/v1/admin/users/11", json={"roles": ["SUPPLY"]})
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
