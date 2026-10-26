"""Выход, CSRF, смена пароля и лимит попыток входа."""

from typing import Annotated

import httpx
import pytest

from tests.backends import PASSWORD
from tests.conftest import ContractChecker, Web


async def test_logout_closes_both_backend_sessions(web: Web, check: ContractChecker) -> None:
    await web.login()
    sid = web.sid

    response = await web.send("POST", "/api/v1/auth/logout")

    assert response.status_code == 204
    check(response, "/auth/logout", "post")
    assert f"session:{sid}" not in web.redis.session_keys()
    assert web.be.crm_logout.calls.last.request.headers["cookie"] == "rt_refresh=crm-refresh-1"
    erp_request = web.be.erp_logout.calls.last.request
    assert erp_request.headers["authorization"].startswith("Bearer ")
    assert erp_request.headers["cookie"] == "refresh_token=erp-refresh-1"
    cleared = [h.lower() for h in response.headers.get_list("set-cookie")]
    assert any(h.startswith("rt_pf_session=") and "max-age=0" in h for h in cleared)


async def test_logout_with_expired_erp_access_refreshes_first(web: Web) -> None:
    await web.login()
    web.clock.advance(301)

    response = await web.send("POST", "/api/v1/auth/logout")

    assert response.status_code == 204
    assert web.be.erp_refresh.call_count == 1
    assert web.be.erp_logout.calls.last.request.headers["cookie"] == "refresh_token=erp-refresh-2"


async def test_logout_succeeds_even_if_backends_fail(web: Web) -> None:
    await web.login()
    web.be.crm_logout.mock(side_effect=httpx.ConnectError("down"))
    web.be.erp_logout.mock(return_value=httpx.Response(500))

    response = await web.send("POST", "/api/v1/auth/logout")

    assert response.status_code == 204
    assert web.redis.session_keys() == []


async def test_logout_without_session(web: Web, check: ContractChecker) -> None:
    response = await web.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "x" * 20})

    assert response.status_code == 401
    check(response, "/auth/logout", "post")


async def test_logout_without_csrf_is_refused(web: Web, check: ContractChecker) -> None:
    await web.login()

    response = await web.client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    check(response, "/auth/logout", "post")
    assert response.json()["code"] == "CSRF_FAILED"
    assert len(web.redis.session_keys()) == 1
    assert web.be.crm_logout.call_count == 0


@pytest.mark.parametrize(
    ("method", "url", "payload", "path"),
    [
        ("POST", "/api/v1/auth/logout", None, "/auth/logout"),
        (
            "POST",
            "/api/v1/auth/change-password",
            {"current_password": PASSWORD, "new_password": "brand-new-pass"},
            "/auth/change-password",
        ),
        ("PATCH", "/api/v1/me", {"language": "uz"}, "/me"),
    ],
)
async def test_mutations_need_the_csrf_token(
    web: Web,
    check: ContractChecker,
    method: str,
    url: str,
    payload: object,
    path: str,
) -> None:
    await web.login()

    missing = await web.client.request(method, url, json=payload)
    wrong = await web.client.request(method, url, json=payload, headers={"X-CSRF-Token": "bad"})
    cookie_value_only = await web.client.request(
        method, url, json=payload, headers={"X-CSRF-Token": web.csrf + "x"}
    )

    for response in (missing, wrong, cookie_value_only):
        assert response.status_code == 403
        check(response, path, method.lower())
        assert response.json()["code"] == "CSRF_FAILED"
    assert web.be.crm_change_password.call_count == 0


async def test_csrf_token_of_another_session_is_refused(web: Web) -> None:
    await web.login()
    other_csrf = web.csrf
    web.client.cookies.clear()
    web.be.profile["email"] = "other.test@example.org"
    await web.login()

    response = await web.send("PATCH", "/api/v1/me", json={"language": "en"}, csrf=other_csrf)

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


async def test_session_is_checked_before_csrf(web: Web) -> None:
    response = await web.client.patch("/api/v1/me", json={"language": "en"})

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


async def test_reads_do_not_need_csrf(web: Web) -> None:
    await web.login()

    assert (await web.client.get("/api/v1/me")).status_code == 200
    assert (await web.client.get("/api/v1/auth/session")).status_code == 200


# --- смена пароля ---------------------------------------------------------------------------------


async def test_change_password_clears_must_change(web: Web, check: ContractChecker) -> None:
    web.be.must_change = True
    login = await web.login()
    assert login.json()["must_change_password"] is True

    response = await web.send(
        "POST",
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "brand-new-pass"},
    )

    assert response.status_code == 204
    check(response, "/auth/change-password", "post")
    sent = web.be.crm_change_password.calls.last.request
    assert sent.headers["authorization"] == "Bearer crm-access-1"
    assert b"brand-new-pass" in sent.content
    web.be.must_change = False
    session = await web.client.get("/api/v1/auth/session")
    assert session.json()["must_change_password"] is False
    assert len(web.redis.session_keys()) == 1  # сессия сохранена


async def test_change_password_wrong_current(web: Web, check: ContractChecker) -> None:
    await web.login()
    web.be.change_password_response = (
        422,
        {"code": "validation_failed", "message": "x", "details": {"reason": "wrong_password"}},
    )

    response = await web.send(
        "POST",
        "/api/v1/auth/change-password",
        json={"current_password": "bad", "new_password": "brand-new-pass"},
    )

    assert response.status_code == 422
    check(response, "/auth/change-password", "post")
    body = response.json()
    assert body["code"] == "WRONG_PASSWORD"
    assert body["source"] == "crm"


async def test_change_password_weak_new(web: Web, check: ContractChecker) -> None:
    await web.login()
    web.be.change_password_response = (
        422,
        {
            "code": "validation_failed",
            "message": "x",
            "details": {"reason": "weak_password", "field": "new_password"},
        },
    )

    response = await web.send(
        "POST",
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "password1"},
    )

    assert response.status_code == 422
    check(response, "/auth/change-password", "post")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["fields"] == ["new_password"]


async def test_change_password_short_new_is_refused_locally(
    web: Web, check: ContractChecker
) -> None:
    await web.login()

    response = await web.send(
        "POST",
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert web.be.crm_change_password.call_count == 0


async def test_other_sections_are_closed_until_password_changed(web: Web) -> None:
    from fastapi import Depends

    from app.deps import Authed, require

    @web.app.get("/api/v1/_probe")
    async def probe(_: Annotated[Authed, Depends(require("dashboard.queue"))]) -> dict[str, bool]:
        return {"ok": True}

    web.be.must_change = True
    await web.login()

    response = await web.client.get("/api/v1/_probe")

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "FORBIDDEN"
    assert body["details"]["reason"] == "password_change_required"


# --- лимит попыток входа --------------------------------------------------------------------------


async def test_login_limit_per_ip(web: Web, check: ContractChecker) -> None:
    statuses = []
    for i in range(12):
        response = await web.login(password="nope", email=f"user{i}@example.org", ip="203.0.113.5")
        statuses.append(response.status_code)

    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]
    assert response.status_code == 429
    check(response, "/auth/login", "post")
    assert response.json()["code"] == "TOO_MANY_REQUESTS"
    assert 0 < int(response.headers["retry-after"]) <= 60
    # CRM об избыточных попытках не узнаёт.
    assert web.be.crm_login.call_count == 10


async def test_login_limit_per_email_across_addresses(web: Web) -> None:
    for i in range(10):
        response = await web.login(password="nope", ip=f"198.51.100.{i}")
        assert response.status_code == 401

    response = await web.login(password="nope", ip="198.51.100.200")

    assert response.status_code == 429


async def test_successful_logins_do_not_count(web: Web) -> None:
    """Офис за одним NAT: много сотрудников входят с одного IP, лимит их не считает (O-1)."""
    for i in range(15):
        web.client.cookies.clear()
        response = await web.login(email=f"user{i}@example.org", ip="203.0.113.9")
        assert response.status_code == 200

    # Счётчики по-прежнему пусты: неверные пароли считаются с нуля.
    for _ in range(10):
        assert (await web.login(password="nope", ip="203.0.113.9")).status_code == 401
    assert (await web.login(password="nope", ip="203.0.113.9")).status_code == 429


async def test_the_same_user_can_log_in_repeatedly(web: Web) -> None:
    for _ in range(15):
        web.client.cookies.clear()
        assert (await web.login(ip="203.0.113.10")).status_code == 200


async def test_failed_logins_count_and_give_429_at_the_threshold(
    web: Web, check: ContractChecker
) -> None:
    for _ in range(10):
        assert (await web.login(password="nope", ip="203.0.113.11")).status_code == 401

    blocked = await web.login(ip="203.0.113.11")  # даже верный пароль: порог исчерпан

    assert blocked.status_code == 429
    check(blocked, "/auth/login", "post")
    assert blocked.json()["code"] == "TOO_MANY_REQUESTS"
    assert web.be.crm_login.call_count == 10


async def test_success_resets_the_email_counter_but_keeps_the_ip_failures(web: Web) -> None:
    for _ in range(9):
        await web.login(password="nope", ip="203.0.113.12")

    assert (await web.login(ip="203.0.113.12")).status_code == 200  # IP: 9 неудач, e-mail: сброс

    web.client.cookies.clear()
    assert (await web.login(password="nope", ip="203.0.113.12")).status_code == 401  # 10-я с IP
    other = await web.login(password="nope", email="other.test@example.org", ip="203.0.113.12")
    assert other.status_code == 429
    # Счётчик e-mail после входа начался заново, поэтому с другого адреса вход открыт.
    assert (await web.login(ip="203.0.113.99")).status_code == 200


async def test_backend_failures_do_not_count(web: Web) -> None:
    web.be.crm_login.mock(side_effect=httpx.ConnectError("down"))
    for _ in range(12):
        response = await web.login(ip="203.0.113.13")
        assert response.status_code == 503

    assert web.be.crm_login.call_count == 12


@pytest.mark.parametrize(
    ("crm_status", "crm_body", "counts"),
    [
        (401, {"code": "invalid_credentials", "message": "x"}, True),
        (423, {"code": "account_locked", "message": "x"}, True),
        (422, {"code": "validation_failed", "message": "x"}, False),
        (429, {"code": "rate_limited", "message": "x"}, False),
    ],
    ids=["invalid_credentials", "account_locked", "validation_failed", "crm_429"],
)
async def test_only_credential_failures_use_up_the_login_limit(
    web: Web, crm_status: int, crm_body: dict[str, object], counts: bool
) -> None:
    """423 ACCOUNT_LOCKED расходует лимит как INVALID_CREDENTIALS; 422 и 429 CRM — нет (Q-T5-1)."""
    web.be.crm_login.mock(
        return_value=httpx.Response(crm_status, headers={"Retry-After": "5"}, json=crm_body)
    )
    ip = "203.0.113.60"
    answers = [(await web.login(password="nope", ip=ip)) for _ in range(12)]

    if counts:
        assert [r.status_code for r in answers[:10]] == [crm_status] * 10
        assert [r.status_code for r in answers[10:]] == [429, 429]
        assert all(r.json()["code"] == "TOO_MANY_REQUESTS" for r in answers[10:])
        assert web.be.crm_login.call_count == 10  # сверх лимита CRM не вызывается
    else:
        assert all(r.status_code == crm_status for r in answers)
        assert web.be.crm_login.call_count == 12  # лимит BFF не сработал


async def test_login_without_platform_role_does_not_count(web: Web) -> None:
    web.be.set_roles([])
    for _ in range(12):
        response = await web.login(ip="203.0.113.14")
        assert response.status_code == 403
        assert response.json()["code"] == "NO_PLATFORM_ROLE"


async def test_login_limit_resets_after_a_minute(web: Web) -> None:
    for _ in range(11):
        await web.login(password="nope", ip="203.0.113.7")

    web.clock.advance(61)
    response = await web.login(ip="203.0.113.7")

    assert response.status_code == 200


async def test_login_limit_email_is_case_insensitive(web: Web) -> None:
    for i in range(10):
        await web.login(password="nope", email="Ivan.Test@Example.org", ip=f"192.0.2.{i}")

    response = await web.login(email="ivan.test@example.org", ip="192.0.2.99")

    assert response.status_code == 429


async def test_rate_key_without_ttl_gets_one(web: Web) -> None:
    """Ключ лимита без срока не должен блокировать вход навсегда."""
    ip = "203.0.113.50"
    web.redis.values[f"rl:login:ip:{ip}"] = "10"  # как если бы EXPIRE не дошёл до Redis

    response = await web.login(password="nope", ip=ip)

    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 60
    assert 0 < await web.redis.ttl(f"rl:login:ip:{ip}") <= 60
    web.clock.advance(61)
    assert (await web.login(ip=ip)).status_code == 200
