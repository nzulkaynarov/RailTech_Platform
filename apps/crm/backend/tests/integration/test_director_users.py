"""Директор читает сотрудников (CRM-01c, Q-PLT-15-1 п. 1; R-1) на настоящем Postgres.

`users:read` даётся вычисленным разделом `admin` (read) роли Платформы — правилом casbin `pr:<id>`,
а не расширением seed `viewer`: SUPPLY и ENGINEER тоже `viewer` и сотрудников читать не должны.
Изменения — только admin.
"""

from collections.abc import Iterator
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration

READ_PATHS = ("/api/v1/users", "/api/v1/users/{target}")
WRITES = (
    ("PATCH", "/api/v1/users/{target}", {"full_name": "Другое имя"}),
    ("POST", "/api/v1/users", {"email": "new@railtech.uz", "full_name": "N", "roles": ["viewer"]}),
    ("POST", "/api/v1/users/{target}/invite", None),
    ("POST", "/api/v1/users/{target}/reset-password", None),
    ("POST", "/api/v1/users/{target}/reset-password/email", None),
)


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        app.state.container.__dict__["user_service"] = UserService(sessions, erp_sync=Queue())
        yield test_client


class Staff(NamedTuple):
    who: dict[str, str]  # заголовки проверяемого сотрудника
    target: int  # id другого сотрудника
    boss: dict[str, str]  # заголовки админа
    who_id: int


async def _staff(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], platform_roles: list[str]
) -> Staff:
    """Сотрудник с ролями Платформы (их выдаёт админ), другой сотрудник-цель и админ."""
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)
    target, _ = await make_user(sessions, "target@railtech.uz", ["manager"])
    who, who_password = await make_user(sessions, "who@railtech.uz", ["viewer"])
    if platform_roles:
        patched = client.patch(
            f"/api/v1/users/{who.id}", json={"platform_roles": platform_roles}, headers=boss
        )
        assert patched.status_code == 200, patched.text
    return Staff(login(client, who.email, who_password), target.id, boss, who.id)


async def test_director_reads_the_staff_list_and_a_card(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    headers, target, *_ = await _staff(client, sessions, ["DIRECTOR"])

    listed = client.get("/api/v1/users", headers=headers)
    card = client.get(f"/api/v1/users/{target}", headers=headers)

    assert listed.status_code == 200, listed.text
    assert {u["email"] for u in listed.json()} >= {"admin@railtech.uz", "target@railtech.uz"}
    assert card.status_code == 200, card.text
    assert card.json()["email"] == "target@railtech.uz"
    permissions = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    assert permissions["users"] == {"read": True, "write": False}


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_director_cannot_change_staff(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    headers, target, *_ = await _staff(client, sessions, ["DIRECTOR"])

    response = client.request(method, path.format(target=target), json=body, headers=headers)

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("roles", [[], ["MANAGER"], ["SUPPLY"], ["ENGINEER"], ["ACCOUNTANT"]])
@pytest.mark.parametrize("path", READ_PATHS)
async def test_other_roles_still_cannot_read_staff(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    roles: list[str],
    path: str,
) -> None:
    """Раздел `admin` матрицы у них hidden: ни базовая роль, ни роль Платформы чтения не дают."""
    headers, target, *_ = await _staff(client, sessions, roles)

    response = client.get(path.format(target=target), headers=headers)

    assert response.status_code == 403, response.text
    permissions = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    assert permissions["users"] == {"read": False, "write": False}


async def test_director_alongside_another_role_keeps_the_grant(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    headers, *_ = await _staff(client, sessions, ["DIRECTOR", "SUPPLY"])

    assert client.get("/api/v1/users", headers=headers).status_code == 200


async def test_taking_the_director_role_away_takes_the_read_away(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    headers, _, boss, who_id = await _staff(client, sessions, ["DIRECTOR"])
    assert client.get("/api/v1/users", headers=headers).status_code == 200
    # Второй директор нужен, иначе первого лишить роли нельзя (409 last_director).
    second, _ = await make_user(sessions, "second@railtech.uz", ["viewer"])
    client.patch(f"/api/v1/users/{second.id}", json={"platform_roles": ["DIRECTOR"]}, headers=boss)

    patched = client.patch(
        f"/api/v1/users/{who_id}", json={"platform_roles": ["SUPPLY"]}, headers=boss
    )

    assert patched.status_code == 200, patched.text
    assert client.get("/api/v1/users", headers=headers).status_code == 403
