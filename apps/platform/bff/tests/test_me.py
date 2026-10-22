"""GET/PATCH /me и /auth/session: роли, вид по активной роли, синхронизация профиля с CRM."""

import json
from typing import Annotated

import httpx
import pytest
from fastapi import Depends

from app import rbac
from app.deps import Authed, require
from tests.conftest import ContractChecker, Web
from tests.rbac_oracle import MATRIX, ROLES, level, union


def expected_resources(roles: list[str]) -> dict[str, str]:
    return {k: union(roles, k) for k in MATRIX if union(roles, k) != "hidden"}


def expected_modules(roles: list[str]) -> list[str]:
    visible = {k.split(".")[0] for k in expected_resources(roles)}
    return [m for m in ("dashboard", "crm", "eds", "erp", "chats", "admin") if m in visible]


@pytest.mark.parametrize("role", ROLES)
async def test_me_for_each_role(web: Web, check: ContractChecker, role: str) -> None:
    await web.login([role])

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    check(response, "/me", "get")
    me = response.json()
    assert me["roles"] == [role]
    assert me["active_role"] is None
    assert me["modules"] == expected_modules([role])
    assert me["resources"] == expected_resources([role])
    assert all(v in ("full", "read") for v in me["resources"].values())  # скрытые не перечисляются
    assert me["restricted_fields"] == rbac.restricted_fields_for([role])
    assert me["language"] == "ru"


async def test_me_unites_several_roles(web: Web, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT", "SUPPLY"])

    me = (await web.client.get("/api/v1/me")).json()

    check(await web.client.get("/api/v1/me"), "/me", "get")
    assert me["roles"] == ["SUPPLY", "ACCOUNTANT"]  # порядок контракта
    assert me["resources"] == expected_resources(["SUPPLY", "ACCOUNTANT"])
    assert me["resources"]["eds.projects"] == "full"  # SUPPLY read + ACCOUNTANT full
    assert me["restricted_fields"] == ["cost_margin", "totals_only", "supplier_prices"]


async def test_session_endpoint_matches_login(web: Web, check: ContractChecker) -> None:
    login = await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/auth/session")

    assert response.status_code == 200
    check(response, "/auth/session", "get")
    assert response.json() == login.json()


async def test_me_without_position_omits_the_field(web: Web, check: ContractChecker) -> None:
    web.be.profile["position"] = None

    response = await web.login(["MANAGER"])

    check(response, "/auth/login", "post")
    assert "position" not in response.json()["me"]


# --- PATCH /me ------------------------------------------------------------------------------------


async def test_patch_language_goes_to_crm(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])

    response = await web.send("PATCH", "/api/v1/me", json={"language": "uz"})

    assert response.status_code == 200
    check(response, "/me", "patch")
    assert response.json()["language"] == "uz"
    sent = web.be.crm_patch_me.calls.last.request
    assert json.loads(sent.content) == {"language": "uz"}
    assert sent.headers["authorization"] == "Bearer crm-access-1"
    assert (await web.client.get("/api/v1/me")).json()["language"] == "uz"
    # Язык хранит CRM: после нового входа он тот же.
    web.client.cookies.clear()
    assert (await web.login()).json()["me"]["language"] == "uz"


async def test_language_comes_from_crm_profile(web: Web) -> None:
    web.be.profile["language"] = "en"

    response = await web.login(["MANAGER"])

    assert response.json()["me"]["language"] == "en"
    web.be.profile["language"] = "uz"
    web.clock.advance(61)
    assert (await web.client.get("/api/v1/me")).json()["language"] == "uz"


async def test_unknown_crm_language_falls_back_to_ru(web: Web) -> None:
    web.be.profile["language"] = "de"

    assert (await web.login(["MANAGER"])).json()["me"]["language"] == "ru"


async def test_patch_language_crm_down_keeps_session_language(web: Web) -> None:
    await web.login(["MANAGER"])
    web.be.crm_patch_me.mock(side_effect=httpx.ConnectError("down"))

    response = await web.send("PATCH", "/api/v1/me", json={"language": "uz"})

    assert response.status_code == 503
    assert response.json()["source"] == "crm"
    assert (await web.client.get("/api/v1/me")).json()["language"] == "ru"


async def test_patch_language_crm_rejects(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    web.be.crm_patch_me.mock(return_value=httpx.Response(422, json={"code": "validation_failed"}))

    response = await web.send("PATCH", "/api/v1/me", json={"language": "uz"})

    assert response.status_code == 422
    check(response, "/me", "patch")
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_patch_active_role_does_not_call_crm(web: Web) -> None:
    await web.login(["MANAGER", "ACCOUNTANT"])

    await web.send("PATCH", "/api/v1/me", json={"active_role": "ACCOUNTANT"})

    assert web.be.crm_patch_me.call_count == 0


async def test_active_role_is_a_view(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER", "ACCOUNTANT"])

    response = await web.send("PATCH", "/api/v1/me", json={"active_role": "ACCOUNTANT"})

    assert response.status_code == 200
    check(response, "/me", "patch")
    me = response.json()
    assert me["roles"] == ["MANAGER", "ACCOUNTANT"]  # роли остаются все
    assert me["active_role"] == "ACCOUNTANT"
    assert me["modules"] == expected_modules(["ACCOUNTANT"])
    assert me["resources"] == expected_resources(["ACCOUNTANT"])
    assert me["restricted_fields"] == ["totals_only", "supplier_prices"]
    assert "crm.leads" not in me["resources"]  # у бухгалтера раздела нет, у менеджера есть

    reset = await web.send("PATCH", "/api/v1/me", json={"active_role": None})
    assert reset.status_code == 200
    assert reset.json()["active_role"] is None
    assert reset.json()["resources"] == expected_resources(["MANAGER", "ACCOUNTANT"])


async def test_active_role_must_be_one_of_own_roles(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])

    for role in ("ADMIN", "BOSS"):
        response = await web.send("PATCH", "/api/v1/me", json={"active_role": role})
        assert response.status_code == 422
        check(response, "/me", "patch")
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert (await web.client.get("/api/v1/me")).json()["active_role"] is None


@pytest.mark.parametrize(
    "payload", [{}, {"language": "fr"}, {"language": None}, {"theme": "dark"}, {"active_role": 5}]
)
async def test_patch_validation(
    web: Web, check: ContractChecker, payload: dict[str, object]
) -> None:
    await web.login(["MANAGER"])

    response = await web.send("PATCH", "/api/v1/me", json=payload)

    assert response.status_code == 422
    check(response, "/me", "patch")
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_patch_active_role_does_not_change_operation_rights(web: Web) -> None:
    """Q-PLT-12-1: активная роль — «вид»; право на операцию считается по объединению ролей."""

    @web.app.get("/api/v1/_op/projects-full")
    async def projects_full(
        _: Annotated[Authed, Depends(require("eds.projects", "full"))],
    ) -> dict[str, bool]:
        return {"ok": True}

    @web.app.get("/api/v1/_op/admin")
    async def admin_read(
        _: Annotated[Authed, Depends(require("admin", "read"))],
    ) -> dict[str, bool]:
        return {"ok": True}

    # DIRECTOR: eds.projects = full; SUPPLY: eds.projects = read.
    await web.login(["DIRECTOR", "SUPPLY"])
    assert level("SUPPLY", "eds.projects") == "read"
    before = (await web.client.get("/api/v1/_op/projects-full")).status_code
    assert before == 200

    patched = await web.send("PATCH", "/api/v1/me", json={"active_role": "SUPPLY"})

    assert patched.json()["resources"]["eds.projects"] == "read"  # вид сузился ...
    assert (await web.client.get("/api/v1/_op/projects-full")).status_code == 200  # ... право нет
    assert (await web.client.get("/api/v1/_op/admin")).status_code == 200  # DIRECTOR: admin = read

    # И наоборот: вид не расширяет права — чужую роль взять нельзя, права не растут.
    assert (await web.send("PATCH", "/api/v1/me", json={"active_role": "ADMIN"})).status_code == 422
    web.client.cookies.clear()
    await web.login(["SUPPLY"])
    assert (await web.client.get("/api/v1/_op/projects-full")).status_code == 403
    assert (await web.client.get("/api/v1/_op/admin")).status_code == 403


# --- синхронизация профиля с CRM ------------------------------------------------------------------


async def test_profile_is_not_reread_within_a_minute(web: Web) -> None:
    await web.login(["MANAGER"])
    calls = web.be.crm_me.call_count

    web.clock.advance(30)
    await web.client.get("/api/v1/me")

    assert web.be.crm_me.call_count == calls


async def test_role_change_in_crm_is_picked_up(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER", "SUPPLY"])
    await web.send("PATCH", "/api/v1/me", json={"active_role": "SUPPLY"})
    web.be.profile["platform_roles"] = ["MANAGER", "DIRECTOR"]
    web.be.profile["position"] = "Заместитель"
    web.clock.advance(61)

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    check(response, "/me", "get")
    me = response.json()
    assert me["roles"] == ["MANAGER", "DIRECTOR"]
    assert me["active_role"] is None  # активной роли больше нет — вид сброшен
    assert me["position"] == "Заместитель"
    assert me["resources"] == expected_resources(["MANAGER", "DIRECTOR"])


async def test_roles_removed_in_crm_close_the_session(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    web.be.profile["platform_roles"] = []
    web.clock.advance(61)

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 403
    assert response.json()["code"] == "NO_PLATFORM_ROLE"
    assert web.redis.session_keys() == []
    assert any(
        h.lower().startswith("rt_pf_session=") and "max-age=0" in h.lower()
        for h in response.headers.get_list("set-cookie")
    )


async def test_erp_access_revoked_and_granted_in_crm(web: Web) -> None:
    await web.login(["MANAGER"])
    web.be.profile["platform_access"] = ["crm"]
    web.clock.advance(61)

    me = (await web.client.get("/api/v1/me")).json()

    assert me["access"] == {"crm": True, "erp": False}
    stored = web.redis.read_session(web.sid)
    assert stored["erp"] is None
    assert stored["erp_state"] == "not_applicable"

    web.be.profile["platform_access"] = ["crm", "erp"]
    web.clock.advance(61)
    me = (await web.client.get("/api/v1/me")).json()
    assert me["access"]["erp"] is True
    assert web.redis.read_session(web.sid)["erp_state"] == "unavailable"  # подключится при вызове


async def test_crm_down_during_profile_sync_uses_the_snapshot(web: Web) -> None:
    await web.login(["DIRECTOR"])
    web.be.crm_me.mock(side_effect=httpx.ConnectError("down"))
    web.clock.advance(61)

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["roles"] == ["DIRECTOR"]


async def test_disabled_employee_is_found_on_profile_sync(web: Web) -> None:
    await web.login(["MANAGER"])
    web.clock.advance(61)
    web.be.crm_me.mock(return_value=httpx.Response(401, json={"code": "auth_failed"}))
    web.be.refresh_status = 401

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"
    assert web.redis.session_keys() == []


async def test_require_notices_role_removed_in_crm_without_me(web: Web) -> None:
    """Снятая в CRM роль перестаёт действовать на защищённых маршрутах и без запроса /me."""

    @web.app.get("/api/v1/_op/leads")
    async def leads(_: Annotated[Authed, Depends(require("crm.leads", "full"))]) -> dict[str, bool]:
        return {"ok": True}

    await web.login(["MANAGER", "DIRECTOR"])
    assert (await web.client.get("/api/v1/_op/leads")).status_code == 200

    web.be.profile["platform_roles"] = ["DIRECTOR"]  # DIRECTOR: crm.leads = read
    web.clock.advance(30)
    assert (await web.client.get("/api/v1/_op/leads")).status_code == 200  # кэш 60 с
    web.clock.advance(31)
    response = await web.client.get("/api/v1/_op/leads")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_require_closes_session_when_all_roles_removed(web: Web) -> None:
    @web.app.get("/api/v1/_op/queue")
    async def queue(_: Annotated[Authed, Depends(require("dashboard.queue"))]) -> dict[str, bool]:
        return {"ok": True}

    await web.login(["MANAGER"])
    web.be.profile["platform_roles"] = []
    web.clock.advance(61)

    response = await web.client.get("/api/v1/_op/queue")

    assert response.status_code == 403
    assert response.json()["code"] == "NO_PLATFORM_ROLE"
    assert web.redis.session_keys() == []
