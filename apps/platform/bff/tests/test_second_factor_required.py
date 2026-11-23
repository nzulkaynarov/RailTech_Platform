"""DV-4b in the BFF: enrollment at sign-in for holders of money and access sections, the fresh
code (step-up) passed to CRM on granting a role, the reset by an administrator.

CRM is on respx; its decisions (who must enroll, codes, lockout) are CRM's, the BFF only relays.
"""

import json

import httpx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.test_admin_users import ADMIN_ID, CrmUsers, crm  # noqa: F401

ENROLL = f"{CRM_URL}/api/v1/auth/login/enroll"


def _crm_requires_enrollment(be: Backends) -> None:
    be.crm_login.mock(
        return_value=httpx.Response(
            202,
            json={"second_factor_required": True, "challenge": "en-1", "enrollment_required": True},
        )
    )

    def setup(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["challenge"] != "en-1":
            return httpx.Response(401, json={"code": "auth_failed", "message": "x", "details": {}})
        return httpx.Response(
            200, json={"secret": "ABC", "otpauth_uri": "otpauth://totp/Demo:ivan?secret=ABC"}
        )

    def enroll(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["challenge"] != "en-1":
            return httpx.Response(401, json={"code": "auth_failed", "message": "x", "details": {}})
        if body["code"] != "123456":
            return httpx.Response(
                401, json={"code": "second_factor_invalid", "message": "x", "details": {}}
            )
        response = be._token_response()
        payload = {**json.loads(response.content), "backup_codes": ["AAAA-BBBB", "CCCC-DDDD"]}
        return httpx.Response(200, json=payload, headers=response.headers)

    be.router.get(f"{CRM_URL}/api/v1/setup/state").mock(
        return_value=httpx.Response(200, json={"needs_setup": False, "company_name": "Demo Rail"})
    )
    be.router.post(f"{ENROLL}/setup").mock(side_effect=setup)
    be.router.post(ENROLL).mock(side_effect=enroll)


async def test_holder_gets_the_enrollment_challenge_not_a_session(
    web: Web, check: ContractChecker
) -> None:
    _crm_requires_enrollment(web.be)

    response = await web.login(["ACCOUNTANT"])

    assert response.status_code == 202
    check(response, "/auth/login", "post")
    assert response.json()["enrollment_required"] is True
    assert not web.redis.session_keys()
    assert "rt_pf_session" not in response.headers.get("set-cookie", "")


async def test_enrollment_opens_the_session_and_shows_backup_codes_once(
    web: Web, check: ContractChecker
) -> None:
    _crm_requires_enrollment(web.be)
    await web.login(["ACCOUNTANT"])

    setup = await web.client.post("/api/v1/auth/login/enroll/setup", json={"challenge": "en-1"})
    assert setup.status_code == 200, setup.text
    check(setup, "/auth/login/enroll/setup", "post")
    assert setup.json()["secret"] == "ABC"

    bad = await web.client.post(
        "/api/v1/auth/login/enroll", json={"challenge": "en-1", "code": "000000"}
    )
    assert bad.status_code == 401
    assert bad.json()["code"] == "SECOND_FACTOR_INVALID"
    stale = await web.client.post(
        "/api/v1/auth/login/enroll", json={"challenge": "old", "code": "123456"}
    )
    assert stale.json()["code"] == "SECOND_FACTOR_EXPIRED"

    done = await web.client.post(
        "/api/v1/auth/login/enroll", json={"challenge": "en-1", "code": "123456"}
    )
    assert done.status_code == 200, done.text
    check(done, "/auth/login/enroll", "post")
    assert done.json()["backup_codes"] == ["AAAA-BBBB", "CCCC-DDDD"]
    assert done.json()["me"]["id"] == "7"
    assert done.headers["cache-control"] == "no-store"
    assert "rt_pf_session" in done.headers.get("set-cookie", "")


async def test_setup_endpoint_signs_the_issuer_with_the_company_name(web: Web) -> None:
    _crm_requires_enrollment(web.be)
    route = web.be.router.post(f"{ENROLL}/setup")
    await web.client.post("/api/v1/auth/login/enroll/setup", json={"challenge": "en-1"})
    assert json.loads(route.calls.last.request.content)["issuer"] == "Demo Rail"


async def test_granting_a_role_passes_the_fresh_code_to_crm(
    web: Web,
    crm: CrmUsers,  # noqa: F811
    check: ContractChecker,
) -> None:
    await web.login(["ADMIN"])
    headers = {"X-CSRF-Token": web.csrf, "X-Step-Up-Token": "fresh"}
    response = await web.client.patch(
        "/api/v1/admin/users/11", json={"position": "x"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert crm.patch_route.calls.last.request.headers["X-Step-Up-Token"] == "fresh"

    without = await web.client.patch(
        "/api/v1/admin/users/11", json={"position": "y"}, headers={"X-CSRF-Token": web.csrf}
    )
    assert without.status_code == 200
    assert "X-Step-Up-Token" not in crm.patch_route.calls.last.request.headers


async def test_crm_step_up_refusal_is_translated(
    web: Web,
    crm: CrmUsers,  # noqa: F811
) -> None:
    await web.login(["ADMIN"])
    crm.update_error = httpx.Response(
        403,
        json={
            "code": "step_up_required",
            "message": "x",
            "details": {"reason": "second_factor_not_enrolled"},
        },
    )
    response = await web.client.patch(
        "/api/v1/admin/users/11", json={"position": "x"}, headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"
    assert response.json()["details"]["reason"] == "second_factor_not_enrolled"


async def test_step_up_endpoint_returns_the_token(web: Web, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])
    web.be.router.post(f"{CRM_URL}/api/v1/me/second-factor/step-up").mock(
        return_value=httpx.Response(200, json={"token": "tok", "expires_in": 300})
    )
    response = await web.client.post(
        "/api/v1/me/second-factor/step-up",
        json={"code": "123456"},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 200
    check(response, "/me/second-factor/step-up", "post")
    assert response.json() == {"token": "tok", "expires_in": 300}


async def test_required_factor_refusal_to_disable_is_readable(web: Web) -> None:
    await web.login(["ACCOUNTANT"])
    web.be.router.post(f"{CRM_URL}/api/v1/me/second-factor/disable").mock(
        return_value=httpx.Response(
            409,
            json={
                "code": "conflict",
                "message": "x",
                "details": {"reason": "second_factor_required"},
            },
        )
    )
    response = await web.client.post(
        "/api/v1/me/second-factor/disable",
        json={"code": "123456"},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "second_factor_required"


async def test_admin_resets_the_factor_with_a_reason(
    web: Web,
    crm: CrmUsers,  # noqa: F811
) -> None:
    await web.login(["ADMIN"])
    route = web.be.router.post(url__regex=rf"{CRM_URL}/api/v1/users/\d+/second-factor/reset$").mock(
        return_value=httpx.Response(204)
    )
    headers = {"X-CSRF-Token": web.csrf}

    response = await web.client.post(
        "/api/v1/admin/users/11/second-factor/reset",
        json={"reason": " lost phone "},
        headers=headers,
    )
    assert response.status_code == 204
    assert json.loads(route.calls.last.request.content) == {"reason": "lost phone"}
    assert route.calls.last.request.url.path.endswith("/users/11/second-factor/reset")

    short = await web.client.post(
        "/api/v1/admin/users/11/second-factor/reset", json={"reason": "x"}, headers=headers
    )
    assert short.status_code == 422
    own = await web.client.post(
        f"/api/v1/admin/users/{ADMIN_ID}/second-factor/reset",
        json={"reason": "my phone"},
        headers=headers,
    )
    assert own.status_code == 409
    assert route.call_count == 1


async def test_reset_needs_the_admin_section(
    web: Web,
    crm: CrmUsers,  # noqa: F811
) -> None:
    await web.login(["MANAGER"])
    response = await web.client.post(
        "/api/v1/admin/users/11/second-factor/reset",
        json={"reason": "lost phone"},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 403
