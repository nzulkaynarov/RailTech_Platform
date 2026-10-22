"""Помощники integration-тестов ролей Платформы: очередь ERP-заглушка, id ролей, аудит."""

from collections.abc import Iterator, Mapping

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog, User
from app.repositories import users as repo
from app.services.platform_roles import PlatformRoleService
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user
from tests.integration.test_platform_access import Queue


def make_client(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, queue: Queue
) -> Iterator[TestClient]:
    """Приложение, у которого сервисы пользователей и ролей ставят задачи ERP в `queue`."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        container.__dict__["user_service"] = UserService(sessions, erp_sync=queue)
        container.__dict__["platform_role_service"] = PlatformRoleService(sessions, erp_sync=queue)
        yield test_client


async def setup_staff(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> tuple[int, dict[str, str]]:
    """Админ (вход) и сотрудник-менеджер без ролей Платформы: (id сотрудника, заголовки админа)."""
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    return employee.id, login(client, admin.email, password)


def role_ids(client: TestClient, headers: dict[str, str]) -> dict[str, int]:
    """Роли каталога по коду (`ADMIN`, `DIRECTOR`, `tpl:MANAGER`, ...) -> id."""
    response = client.get("/api/v1/platform-roles", headers=headers)
    assert response.status_code == 200, response.text
    return {r["code"]: r["id"] for r in response.json() if r["code"]}


def patch_role(
    client: TestClient,
    headers: dict[str, str],
    role_id: object,
    body: Mapping[str, object],
    *,
    version: int | None = None,
) -> Response:
    """PATCH роли с прочитанной версией (R-1b); `version` — подменить, например устаревшую."""
    if version is None:
        current = client.get(f"/api/v1/platform-roles/{role_id}", headers=headers)
        version = current.json()["version"] if current.status_code == 200 else 1
    return client.patch(
        f"/api/v1/platform-roles/{role_id}", json={**body, "version": version}, headers=headers
    )


def legacy_ids(client: TestClient, headers: dict[str, str], codes: list[str]) -> list[int]:
    """Id ролей по старым кодам (`MANAGER` -> `tpl:MANAGER`)."""
    ids = role_ids(client, headers)
    return [ids[c if c in ("ADMIN", "DIRECTOR") else f"tpl:{c}"] for c in codes]


async def audit_rows(sessions: async_sessionmaker[AsyncSession], action: str) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        )
        return list(rows)


async def user_row(sessions: async_sessionmaker[AsyncSession], user_id: int) -> User:
    async with sessions() as session:
        row = await session.get(User, user_id)
        assert row is not None
        return row


async def crm_roles(sessions: async_sessionmaker[AsyncSession], user_id: int) -> list[str]:
    async with sessions() as session:
        return await repo.roles_of(session, user_id)


async def defer_erp_job(sessions: async_sessionmaker[AsyncSession], user_id: int) -> None:
    """Задача `erp_provision_user` в настоящей очереди (как ставит `enqueue_erp_sync`)."""
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('notify', 'erp_provision_user', "
                "0, :lock, NULL, CAST(:args AS jsonb), NULL)::procrastinate_job_to_defer_v1])"
            ),
            {"lock": f"erp_user:{user_id}", "args": f'{{"user_id": {user_id}}}'},
        )
