"""ДОСТ-1п: служебная запись не считается администратором и директором в защите «последнего»."""

import argparse

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import mark_service_users
from app.domain.errors import LastAdminError, LastDirectorError
from app.models.auth import AuditLog, User
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration


async def staff(sessions: async_sessionmaker[AsyncSession], email: str, code: str) -> int:
    account, _ = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, [code])]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    return account.id


async def is_service(sessions: async_sessionmaker[AsyncSession], user_id: int) -> bool:
    async with sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return user.is_service


async def test_service_admin_does_not_keep_the_last_real_admin_deactivatable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    real = await staff(sessions, "real@railtech.uz", "ADMIN")
    service = await staff(sessions, "svc@railtech.uz", "ADMIN")
    users = UserService(sessions)
    await users.update(Actor.system(), service, UserPatch(is_service=True))

    with pytest.raises(LastAdminError):
        await users.update(Actor.system(), real, UserPatch(is_active=False))


async def test_last_real_admin_cannot_be_marked_service(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    real = await staff(sessions, "real@railtech.uz", "ADMIN")
    service = await staff(sessions, "svc@railtech.uz", "ADMIN")
    users = UserService(sessions)
    await users.update(Actor.system(), service, UserPatch(is_service=True))

    with pytest.raises(LastAdminError):
        await users.update(Actor.system(), real, UserPatch(is_service=True))
    assert not await is_service(sessions, real)


async def test_last_real_director_cannot_be_marked_service(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await staff(sessions, "adm@railtech.uz", "ADMIN")
    director = await staff(sessions, "dir@railtech.uz", "DIRECTOR")
    other = await staff(sessions, "svc@railtech.uz", "DIRECTOR")
    users = UserService(sessions)
    await users.update(Actor.system(), other, UserPatch(is_service=True))

    with pytest.raises(LastDirectorError):
        await users.update(Actor.system(), director, UserPatch(is_service=True))
    assert not await is_service(sessions, director)


async def test_admin_can_be_marked_service_while_another_real_admin_remains(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await staff(sessions, "one@railtech.uz", "ADMIN")
    second = await staff(sessions, "two@railtech.uz", "ADMIN")

    await UserService(sessions).update(Actor.system(), second, UserPatch(is_service=True))

    assert await is_service(sessions, second)


async def test_cli_goes_through_the_guard_and_writes_the_audit_log(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = await staff(sessions, "real@railtech.uz", "ADMIN")
    second = await staff(sessions, "two@railtech.uz", "ADMIN")
    plain = await staff(sessions, "plain@railtech.uz", "DIRECTOR")

    class Container:
        session_factory = sessions
        user_service = UserService(sessions)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(mark_service_users, "get_container", lambda: Container())
    args = argparse.Namespace(
        emails=["two@railtech.uz", "real@railtech.uz"], unmark=False, apply=True
    )
    async with sessions() as session:
        before = await session.scalar(select(func.count()).select_from(AuditLog))

    code = await mark_service_users.run(args)

    # Первый по алфавиту — real — помечен, пока остаётся second; затем second — последний.
    assert code == 1
    assert await is_service(sessions, real)
    assert not await is_service(sessions, second)
    assert not await is_service(sessions, plain)
    async with sessions() as session:
        after = await session.scalar(select(func.count()).select_from(AuditLog))
    assert (after or 0) > (before or 0)
