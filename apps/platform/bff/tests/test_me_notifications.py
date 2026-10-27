"""Профиль: личные уведомления от бота и тестовое сообщение (W13-A6, контракт 0.12.0).

`GET/PATCH /me/notification-settings`, `POST /me/test-notification` — доступны каждому вошедшему
(не раздел матрицы). CRM — на respx; решения (бот, Telegram) за CRM, здесь — перевод.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.roles import NAMES

TEST = f"{CRM_URL}/api/v1/me/test-notification"


class CrmMe:
    """`/api/v1/me` CRM: профиль с подписками; PATCH меняет подписки."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.extra: dict[str, Any] = {
            "tg_user_id": 555001,
            "notify_leads": True,
            "notify_system": False,
            "tg_dm_failed_at": None,
        }
        self.patches: list[dict[str, Any]] = []
        self.patch_status = 200
        self.test_response = httpx.Response(200, json={"ok": True})
        self.down = False
        self._get = be._me
        be.crm_me.mock(side_effect=self._profile)
        be.crm_patch_me.mock(side_effect=self._patch)
        self.test_route = be.router.post(TEST).mock(side_effect=self._test)

    def _profile(self, request: httpx.Request) -> httpx.Response:
        if self.down and request.headers.get("x-down-after-login"):
            raise httpx.ConnectError("down")
        response = self._get(request)
        if response.status_code != 200:
            return response
        return httpx.Response(200, json={**response.json(), **self.extra})

    def _patch(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        body = json.loads(request.content)
        self.patches.append(body)
        if self.patch_status != 200:
            return httpx.Response(
                self.patch_status, json={"code": "validation_failed", "message": "x", "details": {}}
            )
        self.extra.update({k: v for k, v in body.items() if k.startswith("notify_")})
        return httpx.Response(200, json={**self.be.profile, **self.extra})

    def _test(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("crm down")
        return self.test_response


@pytest.fixture
def crm_me(be: Backends) -> CrmMe:
    return CrmMe(be)


@pytest.mark.parametrize("role", list(NAMES))
async def test_every_signed_in_employee_reads_own_settings(
    web: Web, crm_me: CrmMe, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.client.get("/api/v1/me/notification-settings")

    assert response.status_code == 200
    check(response, "/me/notification-settings", "get")
    assert response.json() == {
        "telegram_linked": True,
        "notify_leads": True,
        "notify_system": False,
    }


async def test_settings_never_expose_telegram_id(web: Web, crm_me: CrmMe) -> None:
    await web.login(["MANAGER"])

    text = (await web.client.get("/api/v1/me/notification-settings")).text

    assert "555001" not in text
    assert "tg_user_id" not in text


async def test_settings_without_telegram_and_with_delivery_failure(
    web: Web, crm_me: CrmMe, check: ContractChecker
) -> None:
    crm_me.extra.update(tg_user_id=None)
    await web.login(["MANAGER"])
    unlinked = await web.client.get("/api/v1/me/notification-settings")
    crm_me.extra.update(tg_user_id=1, tg_dm_failed_at="2026-10-25T10:00:00Z")
    failed = await web.client.get("/api/v1/me/notification-settings")

    check(unlinked, "/me/notification-settings", "get")
    check(failed, "/me/notification-settings", "get")
    assert unlinked.json()["telegram_linked"] is False
    assert "delivery_failed_at" not in unlinked.json()
    assert failed.json()["delivery_failed_at"] == "2026-10-25T10:00:00Z"


async def test_update_settings_goes_to_crm(web: Web, crm_me: CrmMe, check: ContractChecker) -> None:
    await web.login(["MANAGER"])

    response = await web.send(
        "PATCH", "/api/v1/me/notification-settings", json={"notify_leads": False}
    )

    assert response.status_code == 200
    check(response, "/me/notification-settings", "patch")
    assert crm_me.patches == [{"notify_leads": False}]
    assert response.json()["notify_leads"] is False
    again = await web.client.get("/api/v1/me/notification-settings")
    assert again.json()["notify_leads"] is False


@pytest.mark.parametrize(
    "payload", [{}, {"notify_leads": None}, {"notify_leads": "yes"}, {"language": "ru"}]
)
async def test_update_settings_is_validated(
    web: Web, crm_me: CrmMe, check: ContractChecker, payload: dict[str, Any]
) -> None:
    await web.login(["MANAGER"])

    response = await web.send("PATCH", "/api/v1/me/notification-settings", json=payload)

    assert response.status_code == 422
    check(response, "/me/notification-settings", "patch")
    assert crm_me.patches == []


async def test_update_settings_needs_csrf(web: Web, crm_me: CrmMe) -> None:
    await web.login(["MANAGER"])

    response = await web.send(
        "PATCH", "/api/v1/me/notification-settings", json={"notify_leads": False}, csrf="x" * 20
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert crm_me.patches == []


async def test_settings_require_session(web: Web, crm_me: CrmMe, check: ContractChecker) -> None:
    response = await web.client.get("/api/v1/me/notification-settings")

    assert response.status_code == 401
    check(response, "/me/notification-settings", "get")


async def test_update_settings_when_crm_is_down(
    web: Web, crm_me: CrmMe, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    crm_me.down = True

    response = await web.send(
        "PATCH", "/api/v1/me/notification-settings", json={"notify_leads": False}
    )

    assert response.status_code == 503
    check(response, "/me/notification-settings", "patch")


# --- тестовое уведомление ---


async def test_test_notification_is_sent(web: Web, crm_me: CrmMe, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])

    response = await web.send("POST", "/api/v1/me/test-notification")

    assert response.status_code == 204
    check(response, "/me/test-notification", "post")
    assert crm_me.test_route.call_count == 1
    assert crm_me.test_route.calls.last.request.headers["authorization"].startswith("Bearer ")


@pytest.mark.parametrize(
    ("crm_status", "crm_reason", "code", "status", "reason"),
    [
        (409, "bot_not_configured", "NOT_CONFIGURED", 409, "bot_not_configured"),
        (422, "telegram_not_linked", "CONFLICT", 409, "telegram_not_linked"),
        (409, "telegram_refused", "CONFLICT", 409, "telegram_refused"),
    ],
)
async def test_test_notification_failures_are_named(
    web: Web,
    crm_me: CrmMe,
    check: ContractChecker,
    crm_status: int,
    crm_reason: str,
    code: str,
    status: int,
    reason: str,
) -> None:
    crm_me.test_response = httpx.Response(
        crm_status,
        json={
            "code": "conflict",
            "message": "x",
            "details": {"reason": crm_reason, "telegram_error": "Forbidden: bot was blocked"},
        },
    )
    await web.login(["MANAGER"])

    response = await web.send("POST", "/api/v1/me/test-notification")

    assert response.status_code == status
    check(response, "/me/test-notification", "post")
    assert response.json()["code"] == code
    assert response.json()["source"] == "crm"
    assert response.json()["details"]["reason"] == reason


async def test_test_notification_needs_csrf_and_session(
    web: Web, crm_me: CrmMe, check: ContractChecker
) -> None:
    anonymous = await web.client.post("/api/v1/me/test-notification")
    await web.login(["MANAGER"])
    no_csrf = await web.send("POST", "/api/v1/me/test-notification", csrf="x" * 20)

    assert anonymous.status_code == 401
    assert no_csrf.status_code == 403
    assert crm_me.test_route.call_count == 0


async def test_test_notification_when_crm_is_down(
    web: Web, crm_me: CrmMe, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    crm_me.down = True

    response = await web.send("POST", "/api/v1/me/test-notification")

    assert response.status_code == 503
    check(response, "/me/test-notification", "post")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
