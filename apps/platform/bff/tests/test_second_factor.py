"""ДВ-4: второй фактор входа в BFF — 202 с `challenge`, второй шаг, метка устройства, профиль.

CRM — на respx: пароль верен → 202 без сессии, пока нет метки устройства; код `123456` верен.
"""

import json

import httpx

from tests.backends import PASSWORD, Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

DEVICE = "crm-device-token"


def _crm_with_second_factor(be: Backends) -> None:
    def login(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["password"] != PASSWORD:
            return httpx.Response(401, json={"code": "auth_failed", "message": "x", "details": {}})
        if body.get("device_token") == DEVICE:
            return be._token_response()
        return httpx.Response(202, json={"second_factor_required": True, "challenge": "ch-1"})

    def second(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["challenge"] != "ch-1":
            return httpx.Response(401, json={"code": "auth_failed", "message": "x", "details": {}})
        if body["code"] != "123456":
            return httpx.Response(
                401, json={"code": "second_factor_invalid", "message": "x", "details": {}}
            )
        response = be._token_response()
        payload = json.loads(response.content)
        payload["device_token"] = DEVICE if body.get("remember_device") else None
        return httpx.Response(200, json=payload, headers=response.headers)

    be.crm_login.mock(side_effect=login)
    be.router.post(f"{CRM_URL}/api/v1/auth/login/second-factor").mock(side_effect=second)


async def test_password_step_gives_a_challenge_without_session(
    web: Web, check: ContractChecker
) -> None:
    _crm_with_second_factor(web.be)
    response = await web.login(["MANAGER"])

    assert response.status_code == 202
    check(response, "/auth/login", "post")
    assert response.json() == {
        "second_factor_required": True,
        "challenge": "ch-1",
        "enrollment_required": False,
    }
    assert not web.redis.session_keys()
    assert "rt_pf_session" not in response.headers.get("set-cookie", "")


async def test_code_opens_the_session_and_remembers_the_device(
    web: Web, check: ContractChecker
) -> None:
    _crm_with_second_factor(web.be)
    await web.login(["MANAGER"])

    response = await web.client.post(
        "/api/v1/auth/login/second-factor",
        json={"challenge": "ch-1", "code": "123456", "remember_device": True},
    )

    assert response.status_code == 200, response.text
    check(response, "/auth/login/second-factor", "post")
    assert response.json()["me"]["id"] == "7"
    device = next(h for h in response.headers.get_list("set-cookie") if h.startswith("pf_device="))
    assert "HttpOnly" in device
    assert "Path=/api/v1/auth" in device
    assert "Max-Age=2592000" in device
    assert DEVICE not in response.text  # метка — только в cookie

    again = await web.login(["MANAGER"])
    assert again.status_code == 200  # устройство запомнено: кода не спрашивают


async def test_wrong_and_expired_codes(web: Web) -> None:
    _crm_with_second_factor(web.be)
    await web.login(["MANAGER"])

    wrong = await web.client.post(
        "/api/v1/auth/login/second-factor", json={"challenge": "ch-1", "code": "000000"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "SECOND_FACTOR_INVALID"
    expired = await web.client.post(
        "/api/v1/auth/login/second-factor", json={"challenge": "other", "code": "123456"}
    )
    assert expired.status_code == 401
    assert expired.json()["code"] == "SECOND_FACTOR_EXPIRED"


async def test_profile_setup_enable_disable(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    base = f"{CRM_URL}/api/v1/me/second-factor"
    web.be.router.get(f"{CRM_URL}/api/v1/setup/state").mock(
        return_value=httpx.Response(200, json={"needs_setup": False, "company_name": "Demo Rail"})
    )
    web.be.router.get(base).mock(
        return_value=httpx.Response(
            200, json={"enabled": False, "enabled_at": None, "backup_codes_left": 0}
        )
    )
    setup = web.be.router.post(f"{base}/setup").mock(
        return_value=httpx.Response(
            200, json={"secret": "ABC", "otpauth_uri": "otpauth://totp/Demo:ivan?secret=ABC"}
        )
    )
    web.be.router.post(f"{base}/enable").mock(
        side_effect=lambda request: (
            httpx.Response(200, json={"backup_codes": ["AAAA-BBBB"]})
            if json.loads(request.content)["code"] == "123456"
            else httpx.Response(
                422,
                json={
                    "code": "second_factor_setup_failed",
                    "message": "x",
                    "details": {"reason": "second_factor_code_invalid"},
                },
            )
        )
    )
    web.be.router.post(f"{base}/disable").mock(return_value=httpx.Response(204))
    headers = {"X-CSRF-Token": web.csrf}

    status = await web.client.get("/api/v1/me/second-factor")
    assert status.status_code == 200
    check(status, "/me/second-factor", "get")
    started = await web.client.post("/api/v1/me/second-factor/setup", headers=headers)
    assert started.status_code == 200
    check(started, "/me/second-factor/setup", "post")
    assert json.loads(setup.calls.last.request.content) == {"issuer": "Demo Rail"}
    bad = await web.client.post(
        "/api/v1/me/second-factor/enable", json={"code": "000000"}, headers=headers
    )
    assert bad.status_code == 422
    assert bad.json()["details"]["reason"] == "second_factor_code_invalid"
    ok = await web.client.post(
        "/api/v1/me/second-factor/enable", json={"code": "123456"}, headers=headers
    )
    assert ok.status_code == 200
    assert ok.json() == {"backup_codes": ["AAAA-BBBB"]}
    off = await web.client.post(
        "/api/v1/me/second-factor/disable", json={"code": "123456"}, headers=headers
    )
    assert off.status_code == 204
