"""Admin · Оргструктура: сброс пароля сотрудника по почте (W13-A6, контракт 0.12.0).

`POST /admin/users/{id}/reset-password/email` -> CRM `/users/{id}/reset-password/email`. Решения
(временный пароль, письмо, завершение сессий) — CRM; BFF проверяет `admin: full`, запрещает сброс
себе (до CRM) и переводит ошибки.
"""

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.test_admin_users import ADMIN_ID, CrmUsers, crm, login_as  # noqa: F401

QUEUED = {"email_log_id": 41, "to_email": "анна11@demo.example", "status": "queued"}


class CrmReset:
    def __init__(self, be: Backends) -> None:
        self.response = httpx.Response(200, json=QUEUED)
        self.down = False
        self.route = be.router.post(
            url__regex=rf"{CRM_URL}/api/v1/users/\d+/reset-password/email$"
        ).mock(side_effect=self._reset)

    def _reset(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        return self.response


@pytest.fixture
def reset(be: Backends, crm: CrmUsers) -> CrmReset:  # noqa: F811
    return CrmReset(be)


def error(status: int, code: str, reason: str) -> httpx.Response:
    return httpx.Response(
        status, json={"code": code, "message": code, "details": {"reason": reason}}
    )


async def test_admin_resets_a_password_by_email(
    web: Web, reset: CrmReset, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/11/reset-password/email")

    assert response.status_code == 200
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json() == QUEUED
    sent = reset.route.calls.last.request
    assert sent.url.path == "/api/v1/users/11/reset-password/email"
    assert sent.headers["authorization"].startswith("Bearer crm-access-")
    # Пароль не проходит через BFF: ни в ответе, ни в теле запроса к CRM.
    assert "password" not in response.text.replace("reset-password", "")
    assert not sent.content


async def test_resetting_own_password_is_a_conflict_before_crm(
    web: Web, reset: CrmReset, check: ContractChecker
) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("POST", f"/api/v1/admin/users/{ADMIN_ID}/reset-password/email")

    assert response.status_code == 409
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["source"] == "bff"
    assert response.json()["details"] == {"reason": "self_reset"}
    assert reset.route.call_count == 0


async def test_mail_not_connected_is_not_configured(
    web: Web, reset: CrmReset, check: ContractChecker
) -> None:
    reset.response = error(409, "conflict", "smtp_not_configured")
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/11/reset-password/email")

    assert response.status_code == 409
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["code"] == "NOT_CONFIGURED"
    assert response.json()["details"]["reason"] == "smtp_not_configured"


async def test_missing_secrets_key(web: Web, reset: CrmReset, check: ContractChecker) -> None:
    reset.response = error(409, "conflict", "secrets_key_missing")
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/11/reset-password/email")

    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["code"] == "SECRETS_KEY_MISSING"


async def test_unknown_employee_is_404(web: Web, reset: CrmReset, check: ContractChecker) -> None:
    reset.response = httpx.Response(404, json={"code": "not_found", "message": "x", "details": {}})
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/999/reset-password/email")

    assert response.status_code == 404
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["code"] == "NOT_FOUND"


async def test_crm_unavailable_is_503(web: Web, reset: CrmReset, check: ContractChecker) -> None:
    await login_as(web, "ADMIN")
    reset.down = True

    response = await web.send("POST", "/api/v1/admin/users/11/reset-password/email")

    assert response.status_code == 503
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_only_admin_full_may_reset(
    web: Web, reset: CrmReset, check: ContractChecker, role: str
) -> None:
    await login_as(web, role)

    response = await web.send("POST", "/api/v1/admin/users/11/reset-password/email")

    assert response.status_code == 403
    check(response, "/admin/users/{id}/reset-password/email", "post")
    assert response.json()["details"]["resource"] == "admin"
    assert reset.route.call_count == 0


async def test_reset_needs_csrf_and_session(
    web: Web, reset: CrmReset, check: ContractChecker
) -> None:
    anonymous = await web.client.post("/api/v1/admin/users/11/reset-password/email")
    await login_as(web, "ADMIN")
    no_csrf = await web.send("POST", "/api/v1/admin/users/11/reset-password/email", csrf="x" * 20)

    assert anonymous.status_code == 401
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert reset.route.call_count == 0


async def test_employee_id_must_be_numeric(web: Web, reset: CrmReset) -> None:
    await login_as(web, "ADMIN")

    response = await web.send("POST", "/api/v1/admin/users/abc/reset-password/email")

    assert response.status_code == 422
    assert reset.route.call_count == 0
