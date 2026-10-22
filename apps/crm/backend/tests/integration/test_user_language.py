"""Язык сотрудника (CRM-01b, Q-PLT-10-1 п. 6): `language` в /me, /users и их PATCH."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def test_default_is_ru_and_user_changes_own_language(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)

    assert client.get("/api/v1/me", headers=headers).json()["language"] == "ru"

    response = client.patch("/api/v1/me", json={"language": "uz"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["language"] == "uz"
    assert client.get("/api/v1/me", headers=headers).json()["language"] == "uz"
    async with sessions() as session:
        entries = list(
            await session.scalars(select(AuditLog).where(AuditLog.action == "user.update"))
        )
    assert [(e.before, e.after) for e in entries] == [({"language": "ru"}, {"language": "uz"})]

    # Повтор того же значения не пишет аудит; чужой код — 422.
    assert client.patch("/api/v1/me", json={"language": "uz"}, headers=headers).status_code == 200
    assert client.patch("/api/v1/me", json={"language": "de"}, headers=headers).status_code == 422
    assert client.get("/api/v1/me", headers=headers).json()["language"] == "uz"


async def test_admin_sets_language_of_employee_and_lists_it(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)

    response = client.patch(f"/api/v1/users/{employee.id}", json={"language": "en"}, headers=boss)
    assert response.status_code == 200, response.text
    assert response.json()["language"] == "en"
    listed = {u["email"]: u["language"] for u in client.get("/api/v1/users", headers=boss).json()}
    assert listed == {"admin@railtech.uz": "ru", "dilshod@railtech.uz": "en"}
    assert client.get(f"/api/v1/users/{employee.id}", headers=boss).json()["language"] == "en"

    bad = client.patch(f"/api/v1/users/{employee.id}", json={"language": "xx"}, headers=boss)
    assert bad.status_code == 422


async def test_manager_cannot_change_language_of_another_user(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)

    response = client.patch(f"/api/v1/users/{other.id}", json={"language": "en"}, headers=headers)
    assert response.status_code == 403
