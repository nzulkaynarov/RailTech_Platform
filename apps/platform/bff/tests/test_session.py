"""Сессия: обновление токенов CRM и ERP, отключённый сотрудник, срок жизни, блокировка."""

import asyncio

import httpx
import pytest

from app.auth import AuthService
from app.errors import PlatformError
from app.session import SessionData
from tests.conftest import ContractChecker, Web


def service(web: Web) -> AuthService:
    state = web.app.state
    return AuthService(web.redis, state.crm, state.erp, state.settings)  # type: ignore[arg-type]


async def test_expired_crm_access_is_refreshed(web: Web, check: ContractChecker) -> None:
    await web.login()
    web.clock.advance(601)  # access CRM живёт 600 с; профиль тоже устарел

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    check(response, "/me", "get")
    refresh_request = web.be.crm_refresh.calls.last.request
    assert refresh_request.headers["cookie"] == "rt_refresh=crm-refresh-1"
    stored = web.redis.read_session(web.sid)
    assert stored["crm"]["access"] == "crm-access-2"
    assert stored["crm"]["refresh"] == "crm-refresh-2"  # ротация сохранена
    assert web.be.crm_me.calls.last.request.headers["authorization"] == "Bearer crm-access-2"


async def test_access_is_refreshed_slightly_before_expiry(web: Web) -> None:
    await web.login()
    web.clock.advance(580)  # до истечения 20 с < запаса 30 с

    await web.client.get("/api/v1/me")

    assert web.be.crm_refresh.call_count == 1


async def test_fresh_access_is_not_refreshed(web: Web) -> None:
    await web.login()
    web.clock.advance(120)

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    assert web.be.crm_refresh.call_count == 0


async def test_backend_401_triggers_one_refresh_and_retry(web: Web) -> None:
    await web.login()
    web.clock.advance(61)  # профиль устарел, access ещё жив
    web.be.me_unauthorized_once = True

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 200
    assert web.be.crm_refresh.call_count == 1
    assert web.be.crm_me.call_count == 3  # вход + отказ + повтор


async def test_second_401_after_refresh_ends_the_session(web: Web) -> None:
    await web.login()
    web.clock.advance(61)
    web.be.crm_me.mock(return_value=httpx.Response(401, json={"code": "auth_failed"}))

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"
    assert web.be.crm_refresh.call_count == 1  # одна попытка, не цикл
    assert web.redis.session_keys() == []


async def test_disabled_employee_refresh_401_is_session_expired(
    web: Web, check: ContractChecker
) -> None:
    await web.login()
    web.clock.advance(601)
    web.be.refresh_status = 401  # CRM: пользователь отключён, refresh не принимается

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    check(response, "/me", "get")
    body = response.json()
    assert body["code"] == "SESSION_EXPIRED"
    assert body["source"] == "bff"
    assert web.redis.session_keys() == []
    # Браузеру сбрасываются cookie, следующий запрос тоже 401.
    cleared = [h.lower() for h in response.headers.get_list("set-cookie")]
    assert any(h.startswith("rt_pf_session=") and "max-age=0" in h for h in cleared)
    assert any(h.startswith("rt_pf_csrf=") and "max-age=0" in h for h in cleared)
    web.client.cookies.set("rt_pf_session", "stale", domain="bff.test")
    assert (await web.client.get("/api/v1/me")).status_code == 401


async def test_crm_unavailable_on_refresh_keeps_session(web: Web, check: ContractChecker) -> None:
    await web.login()
    web.clock.advance(601)
    web.be.crm_refresh.mock(side_effect=httpx.ReadTimeout("slow"))

    response = await web.client.get("/api/v1/auth/session")

    # Профиль берётся из снимка, сессия жива.
    assert response.status_code == 200
    check(response, "/auth/session", "get")
    assert len(web.redis.session_keys()) == 1


async def test_session_lifetime_is_absolute(web: Web, check: ContractChecker) -> None:
    await web.login()

    web.clock.advance(12 * 3600 + 1)
    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    check(response, "/me", "get")
    assert response.json()["code"] == "SESSION_EXPIRED"


async def test_no_cookie_is_session_expired(web: Web, check: ContractChecker) -> None:
    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    check(response, "/me", "get")
    assert response.json() == {
        "code": "SESSION_EXPIRED",
        "message": "Сессия истекла. Войдите снова.",
        "source": "bff",
    }


async def test_expired_erp_access_is_refreshed(web: Web) -> None:
    await web.login()
    web.clock.advance(301)  # access ERP живёт 300 с
    svc = service(web)
    sid = web.sid

    response = await svc.call(sid, "erp", "GET", "/api/v1/notifications/")

    assert response.status_code == 200
    refresh_request = web.be.erp_refresh.calls.last.request
    assert refresh_request.headers["cookie"] == "refresh_token=erp-refresh-1"
    stored = web.redis.read_session(sid)
    assert stored["erp"]["refresh"] == "erp-refresh-2"
    sent = web.be.erp_ping.calls.last.request.headers["authorization"].removeprefix("Bearer ")
    assert sent == stored["erp"]["access"]


async def test_erp_refresh_rejected_ends_the_session(web: Web) -> None:
    await web.login()
    web.clock.advance(301)
    web.be.erp_refresh_status = 401
    svc = service(web)

    with pytest.raises(PlatformError) as caught:
        await svc.call(web.sid, "erp", "GET", "/api/v1/notifications/")

    assert caught.value.status_code == 401
    assert caught.value.body.code == "SESSION_EXPIRED"
    assert web.redis.session_keys() == []


async def test_concurrent_requests_refresh_once(web: Web) -> None:
    await web.login()
    web.clock.advance(601)
    svc = service(web)

    results = await asyncio.gather(
        *(svc.call(web.sid, "crm", "GET", "/api/v1/me") for _ in range(5))
    )

    assert [r.status_code for r in results] == [200] * 5
    assert (
        web.be.crm_refresh.call_count == 1
    )  # без блокировки вторая попытка сожгла бы семью токенов


async def test_erp_reconnect_after_it_was_down_at_login(web: Web) -> None:
    web.be.exchange_status = 503
    await web.login()
    svc = service(web)

    with pytest.raises(PlatformError) as caught:
        await svc.call(web.sid, "erp", "GET", "/api/v1/notifications/")

    assert caught.value.status_code == 503
    assert caught.value.body.source == "erp"
    assert web.be.erp_exchange.call_count == 1  # пауза: ERP не долбим

    web.be.exchange_status = 200
    web.clock.advance(16)
    response = await svc.call(web.sid, "erp", "GET", "/api/v1/notifications/")

    assert response.status_code == 200
    stored = web.redis.read_session(web.sid)
    assert stored["erp_state"] == "ok"
    assert stored["erp"]["refresh"].startswith("erp-refresh-")


async def test_erp_call_without_access_is_forbidden(web: Web) -> None:
    web.be.profile["platform_access"] = ["crm"]
    await web.login()
    svc = service(web)

    with pytest.raises(PlatformError) as caught:
        await svc.call(web.sid, "erp", "GET", "/api/v1/notifications/")

    assert caught.value.status_code == 403
    assert caught.value.body.source == "erp"
    assert web.be.erp_ping.call_count == 0


async def test_sources_state(web: Web) -> None:
    await web.login()
    ok = SessionData.model_validate(web.redis.read_session(web.sid))
    assert ok.sources() == {"crm": "ok", "erp": "ok"}

    web.client.cookies.clear()
    web.be.profile["platform_access"] = ["crm"]
    await web.login()
    only_crm = SessionData.model_validate(web.redis.read_session(web.sid))
    assert only_crm.sources() == {"crm": "ok", "erp": "not_applicable"}


async def test_stuck_session_lock_gives_503_not_a_hang(
    web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    await web.login()
    monkeypatch.setattr("app.session.LOCK_WAIT_SECONDS", 0.1)
    web.clock.advance(601)
    await web.redis.set(f"session-lock:{web.sid}", "someone-else", px=15_000)

    with pytest.raises(PlatformError) as caught:
        await service(web).call(web.sid, "crm", "GET", "/api/v1/me")

    assert caught.value.status_code == 503
    assert caught.value.body.code == "BACKEND_UNAVAILABLE"
    assert web.be.crm_refresh.call_count == 0  # без блокировки токены не трогаем


@pytest.mark.parametrize("status", [400, 404, 422, 429, 500, 503])
async def test_refresh_failure_other_than_401_403_keeps_the_session(
    web: Web, check: ContractChecker, status: int
) -> None:
    """Только 401/403 убивают сессию; остальное — сбой бэкенда, 503, сессия жива."""
    await web.login()
    web.clock.advance(601)
    web.be.refresh_status = status
    svc = service(web)

    with pytest.raises(PlatformError) as caught:
        await svc.call(web.sid, "crm", "GET", "/api/v1/me")

    assert caught.value.status_code == 503
    assert caught.value.body.code == "BACKEND_UNAVAILABLE"
    assert caught.value.body.source == "crm"
    assert len(web.redis.session_keys()) == 1


@pytest.mark.parametrize("status", [401, 403])
async def test_refresh_401_403_end_the_session(web: Web, status: int) -> None:
    await web.login()
    web.clock.advance(601)
    web.be.refresh_status = status

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    assert web.redis.session_keys() == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all {",
        '{"csrf": "x", "crm": {"access": "SECRET-ACCESS-VALUE"}}',  # старая схема: нет полей
        "[]",
    ],
)
async def test_unreadable_session_is_treated_as_missing(
    web: Web, check: ContractChecker, raw: str, capsys: pytest.CaptureFixture[str]
) -> None:
    await web.login()
    web.redis.values[f"session:{web.sid}"] = raw

    response = await web.client.get("/api/v1/me")

    assert response.status_code == 401
    check(response, "/me", "get")
    assert response.json()["code"] == "SESSION_EXPIRED"
    assert web.redis.session_keys() == []  # ключ удалён
    assert "SECRET-ACCESS-VALUE" not in response.text
    captured = capsys.readouterr()
    assert "SECRET-ACCESS-VALUE" not in captured.out + captured.err


def test_tokens_are_not_in_repr() -> None:
    data = SessionData.model_validate(
        {
            "csrf": "csrf-secret",
            "created_at": 1,
            "expires_at": 2,
            "user_id": 1,
            "email": "a@b.c",
            "name": "N",
            "platform_roles": ["ADMIN"],
            "platform_access": ["crm"],
            "must_change_password": False,
            "profile_checked_at": 1,
            "crm": {"access": "access-secret", "access_exp": 1, "refresh": "refresh-secret"},
            "erp_state": "not_applicable",
        }
    )

    text = repr(data)

    assert "access-secret" not in text
    assert "refresh-secret" not in text
    assert "csrf-secret" not in text
