"""Вход и доступ (pg): обмен SSO-токена, токен доступа, текущий сотрудник, права, отзыв «сразу»."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends
from sqlalchemy import text

from app.api.deps import require_permission
from app.container import Container
from app.main import create_app
from app.models import Employee
from app.security.access_token import issue_access_token
from app.security.permissions import EdsPermission
from app.services.sso import purge_expired_jti
from tests.conftest import ACCESS_SECRET, SSO_PREVIOUS
from tests.helpers import bearer, seed_employee, sso_token

pytestmark = pytest.mark.pg

EXCHANGE = "/api/v1/auth/sso/exchange"


async def exchange(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(EXCHANGE, json={"token": token})


async def login(client: httpx.AsyncClient, sub: int = 7) -> dict[str, str]:
    response = await exchange(client, sso_token(sub))
    assert response.status_code == 200, response.text
    return bearer(response.json()["access_token"])


def assert_error(response: httpx.Response, status: int, code: str, **details: Any) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert body["source"] == "eds"
    assert isinstance(body["message"], str)
    assert body["message"]
    for key, value in details.items():
        assert body["details"][key] == value
    return body


# --- обмен ---------------------------------------------------------------------------------------------------------


async def test_exchange_issues_access_token_and_me_works(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container)
    response = await exchange(client, sso_token(7))
    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["expires_in"]) == ("bearer", 900)

    me = await client.get("/api/v1/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json() == {
        "crm_user_id": 7,
        "full_name": "Алия Каримова",
        "email": "aliya.karimova@example.com",
        "permissions": ["letters.read", "registry.read"],
    }


async def test_exchange_accepts_previous_secret_during_rotation(
    client: httpx.AsyncClient, container: Container
) -> None:
    await seed_employee(container)
    assert (await exchange(client, sso_token(7, secret=SSO_PREVIOUS))).status_code == 200


async def test_exchange_token_is_one_time(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container)
    token = sso_token(7)
    assert (await exchange(client, token)).status_code == 200
    assert_error(await exchange(client, token), 401, "INVALID_SSO_TOKEN", reason="replayed")
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM sso_jti"))).scalar() == 1


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": "erp"}, "audience"),
        ({"aud": "crm"}, "audience"),
        ({"lifetime": 3600}, "lifetime"),
        ({"now": datetime.now(UTC) - timedelta(minutes=5)}, "expired"),
        ({"secret": "wrong-secret-wrong-secret-wrong-secret-0"}, "signature"),
        ({"sub": "abc"}, "malformed"),
    ],
)
async def test_exchange_rejects_bad_tokens_with_401(
    client: httpx.AsyncClient, container: Container, claims: dict[str, Any], reason: str
) -> None:
    await seed_employee(container)
    assert_error(await exchange(client, sso_token(**claims)), 401, "INVALID_SSO_TOKEN", reason=reason)
    async with container.session_factory() as session:  # отказ до jti: токен не сжигается
        assert (await session.execute(text("SELECT count(*) FROM sso_jti"))).scalar() == 0


async def test_exchange_unknown_user_is_403_and_burns_the_token(
    client: httpx.AsyncClient, container: Container
) -> None:
    token = sso_token(999)
    assert_error(await exchange(client, token), 403, "USER_NOT_PROVISIONED")
    assert_error(await exchange(client, token), 401, "INVALID_SSO_TOKEN", reason="replayed")


async def test_exchange_inactive_user_is_403(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, is_active=False)
    assert_error(await exchange(client, sso_token(7)), 403, "USER_INACTIVE")


async def test_exchange_finds_user_by_sub_only_never_by_email(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, 7, email="boss@example.com")
    token = sso_token(8, email="boss@example.com", name="Boss")  # чужой sub, e-mail существующего сотрудника
    assert_error(await exchange(client, token), 403, "USER_NOT_PROVISIONED")
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM employees"))).scalar() == 1  # обмен не создаёт


async def test_exchange_ignores_permissions_claim(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, permissions={"eds": ["letters.read"]})
    response = await exchange(client, sso_token(7, permissions=["approvals.decide"], role="admin"))
    me = await client.get("/api/v1/me", headers=bearer(response.json()["access_token"]))
    assert me.json()["permissions"] == ["letters.read"]


async def test_exchange_validates_body(client: httpx.AsyncClient) -> None:
    body = assert_error((await client.post(EXCHANGE, json={"token": "short"})), 422, "VALIDATION_FAILED")
    assert body["details"]["fields"][0]["field"] == "token"
    assert_error(await client.post(EXCHANGE, json={"token": "x" * 20, "extra": 1}), 422, "VALIDATION_FAILED")
    assert_error(await client.post(EXCHANGE, content=b"not json"), 422, "VALIDATION_FAILED")


# --- токен доступа и текущий сотрудник ------------------------------------------------------------------------------


async def test_me_requires_a_valid_bearer_token(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container)
    missing = assert_error(await client.get("/api/v1/me"), 401, "UNAUTHORIZED", reason="missing")
    assert missing["details"]["reason"] == "missing"
    assert_error(await client.get("/api/v1/me", headers=bearer("garbage")), 401, "UNAUTHORIZED", reason="malformed")
    forged = issue_access_token(7, "other-secret-other-secret-other-secret-1")
    assert_error(await client.get("/api/v1/me", headers=bearer(forged)), 401, "UNAUTHORIZED", reason="signature")
    old = issue_access_token(7, ACCESS_SECRET, now=datetime.now(UTC) - timedelta(minutes=16))
    assert_error(await client.get("/api/v1/me", headers=bearer(old)), 401, "UNAUTHORIZED", reason="expired")
    basic = await client.get("/api/v1/me", headers={"Authorization": "Basic abc"})
    assert_error(basic, 401, "UNAUTHORIZED")


async def test_me_for_user_missing_from_projection_is_401(client: httpx.AsyncClient) -> None:
    token = issue_access_token(404, ACCESS_SECRET)
    assert_error(await client.get("/api/v1/me", headers=bearer(token)), 401, "UNAUTHORIZED", reason="user_not_found")


async def test_deactivation_and_permission_change_act_immediately(
    client: httpx.AsyncClient, container: Container
) -> None:
    await seed_employee(container)
    headers = await login(client)
    assert (await client.get("/api/v1/me", headers=headers)).json()["permissions"] == ["letters.read", "registry.read"]

    async with container.session_factory() as session, session.begin():
        await session.execute(text("UPDATE employees SET permissions_eds = '{memos.create}'"))
    assert (await client.get("/api/v1/me", headers=headers)).json()["permissions"] == ["memos.create"]

    async with container.session_factory() as session, session.begin():
        await session.execute(text("UPDATE employees SET is_active = false"))
    assert_error(await client.get("/api/v1/me", headers=headers), 403, "USER_INACTIVE")


async def test_me_hides_codes_unknown_to_this_version(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, permissions={"eds": ["letters.read", "future.code"]})
    headers = await login(client)
    assert (await client.get("/api/v1/me", headers=headers)).json()["permissions"] == ["letters.read"]


# --- права ---------------------------------------------------------------------------------------------------------


@pytest.fixture
async def guarded(container: Container) -> Any:
    """Приложение с тестовыми маршрутами за `require_permission` (доменных маршрутов в каркасе нет, E3)."""
    app = create_app(container.settings)

    @app.get("/t/resolve")
    async def resolve(
        _: Annotated[Employee, Depends(require_permission(EdsPermission.LETTERS_RESOLVE))],
    ) -> dict[str, str]:
        return {"ok": "resolve"}

    @app.get("/t/any")
    async def any_of(
        _: Annotated[
            Employee, Depends(require_permission(EdsPermission.MEMOS_APPROVE, EdsPermission.APPROVALS_DECIDE))
        ],
    ) -> dict[str, str]:
        return {"ok": "any"}

    @app.get("/t/open")
    async def anyone(_: Annotated[Employee, Depends(require_permission())]) -> dict[str, str]:
        return {"ok": "open"}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eds.test") as http,
    ):
        yield http


async def test_require_permission(guarded: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, permissions={"eds": ["letters.read"]})
    headers = await login(guarded)

    body = assert_error(
        await guarded.get("/t/resolve", headers=headers), 403, "FORBIDDEN", permission="letters.resolve"
    )
    assert "permissions" not in body["details"]
    body = assert_error(await guarded.get("/t/any", headers=headers), 403, "FORBIDDEN")
    assert body["details"]["permissions"] == ["memos.approve", "approvals.decide"]
    assert (await guarded.get("/t/open", headers=headers)).status_code == 200
    assert_error(await guarded.get("/t/resolve"), 401, "UNAUTHORIZED")

    async with container.session_factory() as session, session.begin():
        await session.execute(text("UPDATE employees SET permissions_eds = '{letters.resolve,approvals.decide}'"))
    assert (await guarded.get("/t/resolve", headers=headers)).status_code == 200
    assert (await guarded.get("/t/any", headers=headers)).status_code == 200  # достаточно любого из прав


# --- уборка jti ------------------------------------------------------------------------------------------------------


async def test_purge_expired_jti(container: Container) -> None:
    now = datetime.now(UTC)
    async with container.session_factory() as session, session.begin():
        for jti, expires in (("old", now - timedelta(minutes=1)), ("fresh", now + timedelta(minutes=9))):
            await session.execute(
                text("INSERT INTO sso_jti (jti, expires_at) VALUES (:j, :e)"),
                {"j": jti + str(uuid.uuid4()), "e": expires},
            )
    async with container.session_factory() as session, session.begin():
        assert await purge_expired_jti(session, now=now) == 1
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM sso_jti"))).scalar() == 1
