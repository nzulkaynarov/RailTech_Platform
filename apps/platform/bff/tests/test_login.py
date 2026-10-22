"""POST /auth/login: сессия, cookie, перехват refresh-токенов CRM и ERP, ошибки."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.errors import retry_after_seconds
from tests.backends import PASSWORD, Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL


async def test_login_manager_with_erp(web: Web, check: ContractChecker) -> None:
    response = await web.login(["MANAGER"])

    assert response.status_code == 200
    check(response, "/auth/login", "post")
    body = response.json()
    assert body["must_change_password"] is False
    assert body["me"]["roles"] == ["MANAGER"]
    assert body["me"]["access"] == {"crm": True, "erp": True}
    assert body["me"]["id"] == "7"
    assert body["me"]["initials"] == "ИТ"
    assert body["me"]["position"] == "Менеджер по продажам"

    # Токены бэкендов не уходят в браузер: ни в теле, ни в cookie.
    assert "crm-access" not in response.text
    assert "crm-refresh" not in response.text
    assert "erp-refresh" not in response.text
    for header in response.headers.get_list("set-cookie"):
        assert "crm-refresh" not in header
        assert "erp-refresh" not in header

    # В Redis — оба набора токенов и refresh-cookie CRM, как их выдали бэкенды.
    (key,) = web.redis.session_keys()
    stored = web.redis.read_session(key.removeprefix("session:"))
    assert stored["crm"]["refresh"] == "crm-refresh-1"
    assert stored["erp"]["refresh"] == "erp-refresh-1"
    assert stored["erp_state"] == "ok"
    assert stored["csrf"] == web.csrf


async def test_session_cookies_attributes(web: Web) -> None:
    response = await web.login()

    cookies = {h.split("=", 1)[0]: h.lower() for h in response.headers.get_list("set-cookie")}
    session, csrf = cookies["rt_pf_session"], cookies["rt_pf_csrf"]
    for header in (session, csrf):
        assert "secure" in header
        assert "samesite=lax" in header
        assert "path=/" in header
        assert "max-age=43200" in header  # PLATFORM_SESSION_TTL_HOURS = 12 по умолчанию
    assert "httponly" in session
    assert "httponly" not in csrf  # CSRF-значение читает скрипт SPA
    assert len(web.sid) >= 43  # 256 бит в base64url


async def test_session_ttl_in_redis_matches_setting(web: Web) -> None:
    await web.login()

    assert await web.redis.ttl(f"session:{web.sid}") == 12 * 3600


async def test_request_id_reaches_crm_and_erp(web: Web) -> None:
    await web.client.post(
        "/api/v1/auth/login",
        json={"email": "ivan.test@example.org", "password": PASSWORD},
        headers={"X-Request-Id": "trace-777"},
    )

    for route in (web.be.crm_login, web.be.crm_me, web.be.crm_sso, web.be.erp_exchange):
        assert route.calls.last.request.headers["x-request-id"] == "trace-777"


async def test_erp_exchange_gets_crm_sso_token(web: Web) -> None:
    await web.login()

    assert web.be.crm_sso.calls.last.request.headers["authorization"] == "Bearer crm-access-1"
    assert b"sso-token-1" in web.be.erp_exchange.calls.last.request.content


async def test_wrong_password(web: Web, check: ContractChecker) -> None:
    response = await web.login(password="nope")

    assert response.status_code == 401
    check(response, "/auth/login", "post")
    body = response.json()
    assert body["code"] == "INVALID_CREDENTIALS"
    assert body["source"] == "crm"
    assert web.redis.session_keys() == []
    assert response.headers.get_list("set-cookie") == []


async def test_user_without_platform_role_is_refused(web: Web, check: ContractChecker) -> None:
    response = await web.login([])

    assert response.status_code == 403
    check(response, "/auth/login", "post")
    assert response.json()["code"] == "NO_PLATFORM_ROLE"
    assert web.redis.session_keys() == []
    # Выданную CRM сессию не оставляем висеть.
    assert web.be.crm_logout.call_count == 1
    assert "rt_refresh=crm-refresh-1" in web.be.crm_logout.calls.last.request.headers["cookie"]
    assert web.be.crm_sso.call_count == 0


async def test_unknown_platform_role_codes_do_not_count(web: Web) -> None:
    response = await web.login(["SUPERUSER"])

    assert response.status_code == 403
    assert response.json()["code"] == "NO_PLATFORM_ROLE"


async def test_staff_without_erp_access(web: Web, check: ContractChecker) -> None:
    web.be.profile["platform_access"] = ["crm"]

    response = await web.login(["MANAGER"])

    assert response.status_code == 200
    check(response, "/auth/login", "post")
    assert response.json()["me"]["access"] == {"crm": True, "erp": False}
    assert web.be.crm_sso.call_count == 0
    assert web.be.erp_exchange.call_count == 0
    stored = web.redis.read_session(web.sid)
    assert stored["erp"] is None
    assert stored["erp_state"] == "not_applicable"


async def test_crm_unavailable(web: Web, check: ContractChecker) -> None:
    web.be.crm_login.mock(side_effect=httpx.ConnectError("down"))

    response = await web.login()

    assert response.status_code == 503
    check(response, "/auth/login", "post")
    body = response.json()
    assert body["code"] == "BACKEND_UNAVAILABLE"
    assert body["source"] == "crm"
    assert web.redis.session_keys() == []


async def test_crm_server_error_is_unavailable(web: Web) -> None:
    web.be.login_status = 502

    response = await web.login()

    assert response.status_code == 503
    assert response.json()["source"] == "crm"


async def test_locked_account_is_account_locked(web: Web, check: ContractChecker) -> None:
    web.be.login_status = 423

    response = await web.login()

    assert response.status_code == 423
    check(response, "/auth/login", "post")
    body = response.json()
    assert body["code"] == "ACCOUNT_LOCKED"
    assert body["source"] == "crm"
    assert response.headers["retry-after"] == "60"  # CRM срок не назвал


async def test_locked_account_retry_after_from_until(web: Web, check: ContractChecker) -> None:
    until = datetime.fromtimestamp(web.clock() + 900, UTC).isoformat()
    web.be.crm_login.mock(
        return_value=httpx.Response(
            423, json={"code": "account_locked", "message": "x", "details": {"until": until}}
        )
    )

    response = await web.login()

    assert response.status_code == 423
    check(response, "/auth/login", "post")
    assert 1 <= int(response.headers["retry-after"]) <= 900_000_000  # целое число секунд


@pytest.mark.parametrize(
    ("header", "expected"),
    [("120", 120), ("30.5", 30), ("0", 1), ("garbage", 60)],
)
def test_retry_after_is_normalised_to_integer(header: str, expected: int) -> None:
    response = httpx.Response(429, headers={"Retry-After": header}, json={})

    assert retry_after_seconds(response) == expected


def test_retry_after_http_date_and_missing() -> None:
    soon = datetime.now(UTC) + timedelta(seconds=300)
    response = httpx.Response(429, headers={"Retry-After": format_datetime(soon, usegmt=True)})

    assert 290 <= retry_after_seconds(response) <= 300
    assert retry_after_seconds(httpx.Response(429, json={})) == 60


async def test_backend_429_on_login_keeps_integer_retry_after(
    web: Web, check: ContractChecker
) -> None:
    web.be.crm_login.mock(
        return_value=httpx.Response(429, headers={"Retry-After": "17.9"}, json={"code": "rate"})
    )

    response = await web.login()

    assert response.status_code == 429
    check(response, "/auth/login", "post")
    assert response.headers["retry-after"] == "17"
    assert response.json()["code"] == "TOO_MANY_REQUESTS"


async def test_erp_down_does_not_block_login(web: Web, check: ContractChecker) -> None:
    web.be.exchange_status = 503

    response = await web.login(["MANAGER"])

    assert response.status_code == 200
    check(response, "/auth/login", "post")
    assert response.json()["me"]["access"]["erp"] is True
    stored = web.redis.read_session(web.sid)
    assert stored["erp_state"] == "unavailable"
    assert stored["erp"] is None


async def test_erp_sso_refused_does_not_block_login(web: Web) -> None:
    web.be.sso_status = 403

    response = await web.login()

    assert response.status_code == 200
    assert web.redis.read_session(web.sid)["erp_state"] == "unavailable"


async def test_validation_errors(web: Web, check: ContractChecker) -> None:
    for payload in (
        {},
        {"email": "no-at-sign", "password": "x"},
        {"email": "a@b.c", "password": ""},
    ):
        response = await web.client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert web.be.crm_login.call_count == 0


async def test_cookies_of_backends_do_not_leak_between_employees(web: Web) -> None:
    """Общий httpx-клиент не хранит cookie CRM и ERP: токен одного не уходит в запрос другого."""
    await web.login(["MANAGER"])
    web.client.cookies.clear()

    await web.login(["DIRECTOR"], email="petr.test@example.org")

    second_login = web.be.crm_login.calls.last.request
    assert "cookie" not in second_login.headers
    assert "cookie" not in web.be.erp_exchange.calls.last.request.headers


async def test_relogin_closes_previous_session(web: Web) -> None:
    await web.login()
    first = web.sid

    response = await web.login()

    assert response.status_code == 200
    assert web.sid != first
    assert f"session:{first}" not in web.redis.session_keys()
    assert web.redis.session_keys() == [f"session:{web.sid}"]
    assert web.be.crm_logout.call_count == 1
    assert "crm-refresh-1" in web.be.crm_logout.calls.last.request.headers["cookie"]
    assert web.be.erp_logout.call_count == 1


async def test_crm_url_is_the_configured_one(web: Web) -> None:
    await web.login()

    assert str(web.be.crm_login.calls.last.request.url) == f"{CRM_URL}/api/v1/auth/login"


async def test_redis_down_is_backend_unavailable(
    client: httpx.AsyncClient, be: Backends, check: ContractChecker
) -> None:
    """Без Redis сессию не завести: честный 503, а не 500."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ivan.test@example.org", "password": PASSWORD}
    )

    assert response.status_code == 503
    check(response, "/auth/login", "post")
    body = response.json()
    assert body["code"] == "BACKEND_UNAVAILABLE"
    assert body["source"] == "bff"
    assert be.crm_login.call_count == 0


@pytest.mark.parametrize(
    "path", ["/api/v1/auth/session", "/api/v1/me", "/api/v1/menu-counters", "/api/v1/notifications"]
)
async def test_redis_down_with_a_session_cookie_is_503_not_500(
    client: httpx.AsyncClient, check: ContractChecker, path: str
) -> None:
    """S0-2: `redis-cache` лёг — сессии недоступны (ожидаемо), но ответ честный 503, а не 500."""
    client.cookies.set("rt_pf_session", "any-sid")
    response = await client.get(path)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "BACKEND_UNAVAILABLE"
    assert body["source"] == "bff"
