"""CLI `create-admin` (CRM-01b): админ — сотрудник Платформы (ADMIN).

Новый админ получает `["ADMIN"]`; восстановление существующего сохраняет его роли Платформы и
добавляет `ADMIN`; доступ `crm+erp`; повтор идемпотентен; сбой очереди не роняет команду.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.auth import User
from app.models.platform_roles import UserPlatformRole
from app.repositories import platform_roles as platform_repo
from app.repositories import users as repo
from app.services.users import UserService
from tests.integration.crm_helpers import make_user
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration

PASSWORD = "Sup3rSecretPass"


async def _state(
    sessions: async_sessionmaker[AsyncSession], email: str
) -> tuple[int, list[str], list[str], list[str]]:
    async with sessions() as session:
        user = await repo.by_email(session, email)
        assert user is not None
        held = await platform_repo.roles_of_user(session, user.id)
        return (
            user.id,
            [r.code or r.name for r in held],
            user.platform_access,
            await repo.roles_of(session, user.id),
        )


async def test_new_admin_gets_platform_admin_erp_access_and_provisioning(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue()
    service = UserService(sessions, erp_sync=queue)

    await service.bootstrap_admin("boss@railtech.uz", "Босс", PASSWORD)

    user_id, platform_roles, access, roles = await _state(sessions, "boss@railtech.uz")
    assert (platform_roles, access, roles) == (["ADMIN"], ["crm", "erp"], ["admin"])
    assert queue.jobs == [("provision", user_id)]


async def test_restoring_existing_user_keeps_platform_roles_and_adds_admin(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue()
    user, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        (manager,) = await platform_repo.by_codes(session, ["tpl:MANAGER"])
        session.add(UserPlatformRole(user_id=user.id, role_id=manager.id))
    service = UserService(sessions, erp_sync=queue)

    await service.bootstrap_admin("dilshod@railtech.uz", "Дилшод", PASSWORD)

    _, platform_roles, access, roles = await _state(sessions, "dilshod@railtech.uz")
    assert (platform_roles, access, roles) == (
        ["ADMIN", "tpl:MANAGER"],
        ["crm", "erp"],
        ["admin"],
    )
    assert queue.jobs == [("provision", user.id)]


async def test_repeat_is_idempotent_and_queue_failure_does_not_fail_the_command(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue()
    service = UserService(sessions, erp_sync=queue)
    await service.bootstrap_admin("boss@railtech.uz", "Босс", PASSWORD)
    first = await _state(sessions, "boss@railtech.uz")

    queue.broken = True  # очередь недоступна: ошибка оседает в erp_sync_error, команда не падает
    await service.bootstrap_admin("boss@railtech.uz", "Босс", PASSWORD)

    assert await _state(sessions, "boss@railtech.uz") == first
    async with sessions() as session:
        row = await session.get(User, first[0])
        assert row is not None
        assert row.erp_sync_error is not None
