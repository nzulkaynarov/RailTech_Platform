"""DV-4b on a real Postgres: the second factor is mandatory by permission sections (enrollment at
sign-in), the administrator resets it with a journal entry, a fresh code (step-up) guards granting
a role and confirming bank details, disabling a required factor is refused."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.users import UserPatch, UserService
from tests.integration.crm_helpers import PASSWORD, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("s" * 64)})
    with TestClient(create_app(settings)) as test_client:
        yield test_client


async def give_role(sessions: async_sessionmaker[AsyncSession], user_id: int, code: str) -> int:
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, [code])]
    await UserService(sessions).update(Actor.system(), user_id, UserPatch(platform_role_ids=ids))
    return ids[0]


def password_login(client: TestClient, email: str) -> Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})


def enroll(client: TestClient, email: str) -> tuple[dict[str, str], str, list[str]]:
    """Sign in a holder who must enroll; returns headers, the secret and the backup codes."""
    first = password_login(client, email)
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["enrollment_required"] is True
    setup = client.post(
        "/api/v1/auth/login/enroll/setup", json={"challenge": body["challenge"], "issuer": "RT"}
    )
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    done = client.post(
        "/api/v1/auth/login/enroll",
        json={"challenge": body["challenge"], "code": pyotp.TOTP(secret).now()},
    )
    assert done.status_code == 200, done.text
    assert len(done.json()["backup_codes"]) == 8
    return (
        {"Authorization": f"Bearer {done.json()['access_token']}"},
        secret,
        done.json()["backup_codes"],
    )


def next_code(secret: str) -> str:
    """The code of the next 30 s step: accepted once, after the one that just enabled the factor."""
    return pyotp.TOTP(secret).at(datetime.now(UTC) + timedelta(seconds=30))


async def audit_rows(sessions: async_sessionmaker[AsyncSession], action: str) -> list[AuditLog]:
    async with sessions() as session:
        stmt = select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        return list((await session.scalars(stmt)).all())


async def test_holder_cannot_sign_in_without_the_factor(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    holder, _ = await make_user(sessions, "acc@railtech.uz", ["viewer"])
    plain, _ = await make_user(sessions, "mgr@railtech.uz", ["viewer"])
    await give_role(sessions, holder.id, "tpl:ACCOUNTANT")
    await give_role(sessions, plain.id, "tpl:MANAGER")

    refused = password_login(client, holder.email)
    assert refused.status_code == 202
    assert "access_token" not in refused.json()
    assert refused.json()["enrollment_required"] is True
    assert "rt_refresh" not in client.cookies
    assert password_login(client, plain.email).status_code == 200


async def test_pilot_universal_manager_is_covered(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    pilot, _ = await make_user(sessions, "pilot@railtech.uz", ["viewer"])
    await give_role(sessions, pilot.id, "tpl:MANAGER_ALL")
    assert password_login(client, pilot.email).status_code == 202


async def test_enrollment_at_sign_in_then_the_code_is_asked(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    holder, _ = await make_user(sessions, "dir@railtech.uz", ["viewer"])
    await give_role(sessions, holder.id, "DIRECTOR")
    first = password_login(client, holder.email).json()
    setup = client.post("/api/v1/auth/login/enroll/setup", json={"challenge": first["challenge"]})
    secret = setup.json()["secret"]
    wrong = client.post(
        "/api/v1/auth/login/enroll", json={"challenge": first["challenge"], "code": "000000"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "second_factor_invalid"
    # a login challenge cannot be used for enrollment and vice versa
    assert (
        client.post(
            "/api/v1/auth/login/enroll", json={"challenge": "junk", "code": "123456"}
        ).status_code
        == 401
    )

    done = client.post(
        "/api/v1/auth/login/enroll",
        json={"challenge": first["challenge"], "code": pyotp.TOTP(secret).now()},
    )
    assert done.status_code == 200
    status = client.get(
        "/api/v1/me/second-factor",
        headers={"Authorization": f"Bearer {done.json()['access_token']}"},
    ).json()
    assert status == {**status, "enabled": True, "required": True}

    again = password_login(client, holder.email)
    assert again.status_code == 202
    assert again.json()["enrollment_required"] is False
    # the enrollment challenge is spent once the factor exists
    reused = client.post(
        "/api/v1/auth/login/enroll",
        json={"challenge": first["challenge"], "code": next_code(secret)},
    )
    assert reused.status_code == 401


async def test_role_change_makes_the_factor_required_but_not_mid_session(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    person, _ = await make_user(sessions, "grow@railtech.uz", ["viewer"])
    await give_role(sessions, person.id, "tpl:MANAGER")
    first = password_login(client, person.email)
    assert first.status_code == 200
    await give_role(sessions, person.id, "tpl:ACCOUNTANT")
    # the session opened before the role change keeps working until it expires
    assert client.post("/api/v1/auth/refresh").status_code == 200
    client.cookies.clear()
    assert password_login(client, person.email).status_code == 202


async def test_required_factor_cannot_be_switched_off(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    holder, _ = await make_user(sessions, "acc2@railtech.uz", ["viewer"])
    await give_role(sessions, holder.id, "tpl:ACCOUNTANT")
    headers, _, backup = enroll(client, holder.email)
    off = client.post("/api/v1/me/second-factor/disable", json={"code": backup[0]}, headers=headers)
    assert off.status_code == 409
    assert off.json()["details"]["reason"] == "second_factor_required"
    assert client.get("/api/v1/me/second-factor", headers=headers).json()["enabled"] is True


async def test_admin_reset_is_journaled_and_the_employee_enrolls_again(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    victim, _ = await make_user(sessions, "lostphone@railtech.uz", ["viewer"])
    await give_role(sessions, victim.id, "tpl:ACCOUNTANT")
    _, _, _ = enroll(client, victim.email)
    client.cookies.clear()
    # the administrator himself is a legacy admin without platform roles: no factor is asked
    admin = {"Authorization": "Bearer " + password_login(client, boss.email).json()["access_token"]}

    short = client.post(
        f"/api/v1/users/{victim.id}/second-factor/reset", json={"reason": "x"}, headers=admin
    )
    assert short.status_code == 422
    own = client.post(
        f"/api/v1/users/{boss.id}/second-factor/reset", json={"reason": "my phone"}, headers=admin
    )
    assert own.status_code == 409
    reset = client.post(
        f"/api/v1/users/{victim.id}/second-factor/reset",
        json={"reason": "phone lost, confirmed by call"},
        headers=admin,
    )
    assert reset.status_code == 204, reset.text
    rows = await audit_rows(sessions, "auth.second_factor_reset")
    assert [(r.entity_id, r.actor_user_id, (r.after or {}).get("reason")) for r in rows] == [
        (str(victim.id), boss.id, "phone lost, confirmed by call")
    ]
    again = client.post(
        f"/api/v1/users/{victim.id}/second-factor/reset", json={"reason": "twice"}, headers=admin
    )
    assert again.status_code == 422
    # no factor any more: the next sign-in is the enrollment, not the password alone
    client.cookies.clear()
    assert password_login(client, victim.email).json()["enrollment_required"] is True


async def test_reset_requires_the_users_write_right(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    viewer, _ = await make_user(sessions, "viewer1@railtech.uz", ["viewer"])
    target, _ = await make_user(sessions, "target1@railtech.uz", ["viewer"])
    headers = {
        "Authorization": "Bearer " + password_login(client, viewer.email).json()["access_token"]
    }
    denied = client.post(
        f"/api/v1/users/{target.id}/second-factor/reset",
        json={"reason": "no right"},
        headers=headers,
    )
    assert denied.status_code == 403


async def admin_with_factor(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], email: str
) -> tuple[dict[str, str], str]:
    boss, _ = await make_user(sessions, email, ["viewer"])
    await give_role(sessions, boss.id, "ADMIN")
    headers, secret, _ = enroll(client, boss.email)
    return headers, secret


async def test_granting_a_role_needs_a_fresh_code(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    headers, secret = await admin_with_factor(client, sessions, "root@railtech.uz")
    target, _ = await make_user(sessions, "newbie@railtech.uz", ["viewer"])
    async with sessions() as session:
        manager, supply = [
            r.id for r in await prepo.by_codes(session, ["tpl:MANAGER", "tpl:SUPPLY"])
        ]

    denied = client.patch(
        f"/api/v1/users/{target.id}", json={"platform_role_ids": [manager]}, headers=headers
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "step_up_required"

    wrong = client.post(
        "/api/v1/me/second-factor/step-up", json={"code": "000000"}, headers=headers
    )
    assert wrong.status_code == 422
    fresh = client.post(
        "/api/v1/me/second-factor/step-up", json={"code": next_code(secret)}, headers=headers
    )
    assert fresh.status_code == 200, fresh.text
    token = {"X-Step-Up-Token": fresh.json()["token"]}
    assert fresh.json()["expires_in"] == 300

    granted = client.patch(
        f"/api/v1/users/{target.id}",
        json={"platform_role_ids": [manager]},
        headers={**headers, **token},
    )
    assert granted.status_code == 200, granted.text
    # taking roles away and editing other fields need no fresh code
    revoked = client.patch(
        f"/api/v1/users/{target.id}", json={"full_name": "New Name"}, headers=headers
    )
    assert revoked.status_code == 200
    # a token of another employee is stale for this one
    other, _ = await make_user(sessions, "other@railtech.uz", ["viewer"])
    await give_role(sessions, other.id, "ADMIN")
    o_headers, o_secret, _ = enroll(client, other.email)
    o_token = client.post(
        "/api/v1/me/second-factor/step-up", json={"code": next_code(o_secret)}, headers=o_headers
    ).json()["token"]
    stolen = client.patch(
        f"/api/v1/users/{target.id}",
        json={"platform_role_ids": [manager, supply]},
        headers={**headers, "X-Step-Up-Token": o_token},
    )
    assert stolen.status_code == 403
    # creating an employee with a role is granting a role too
    body = {"email": "fresh@railtech.uz", "full_name": "Fresh", "platform_role_ids": [manager]}
    assert client.post("/api/v1/users", json=body, headers=headers).status_code == 403
    assert client.post("/api/v1/users", json=body, headers={**headers, **token}).status_code == 201


async def test_step_up_check_guards_bank_details(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    headers, secret = await admin_with_factor(client, sessions, "root2@railtech.uz")
    check = "/api/v1/me/second-factor/step-up/check"
    assert client.post(check, headers=headers).status_code == 403
    assert client.post(check, headers={**headers, "X-Step-Up-Token": "junk"}).status_code == 403
    token = client.post(
        "/api/v1/me/second-factor/step-up", json={"code": next_code(secret)}, headers=headers
    ).json()["token"]
    assert client.post(check, headers={**headers, "X-Step-Up-Token": token}).status_code == 204


async def test_step_up_for_a_holder_who_never_enrolled_points_to_enrollment(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A session opened before the rule: the sensitive action sends him to enrollment."""
    holder, _ = await make_user(sessions, "old@railtech.uz", ["viewer"])
    headers = {
        "Authorization": "Bearer " + password_login(client, holder.email).json()["access_token"]
    }
    await give_role(sessions, holder.id, "tpl:ACCOUNTANT")  # role arrives mid-session
    denied = client.post("/api/v1/me/second-factor/step-up/check", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["details"]["reason"] == "second_factor_not_enrolled"


async def test_without_the_encryption_key_nobody_is_locked_out(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """No `SECRETS_KEY`: no factor can exist, so the rule stays inactive instead of locking out."""
    holder, _ = await make_user(sessions, "nokey@railtech.uz", ["viewer"])
    await give_role(sessions, holder.id, "DIRECTOR")
    with TestClient(create_app(live_settings)) as keyless:
        assert password_login(keyless, holder.email).status_code == 200
