"""Роли Платформы в CRM (CRM-01, ADR-0011) на настоящем Postgres: `platform_roles` и `position`.

Роли Платформы вычисляют роль CRM, доступ к ERP и роли ERP (таблица `platform-rbac.yaml`); сквозной
путь: PATCH/POST /users -> `user_roles`, `platform_access`, `erp_role_codes`, очередь провижининга,
аудит, `/me` и `/users`, инвариант «≥ 1 активный admin», первый админ из /setup.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog, User
from app.repositories import users as repo
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration

# (роль Платформы) -> (базовая роль CRM, role_codes, platform_access) по таблице контракта.
TABLE = {
    "MANAGER": ("manager", ["VIEWER"]),
    "DIRECTOR": ("viewer", ["HEAD"]),
    "SUPPLY": ("viewer", ["CATALOG_SUPPLY", "FULFILLMENT"]),
    "ENGINEER": ("viewer", ["FULFILLMENT"]),
    "ACCOUNTANT": ("manager", ["FINANCE"]),
    "ADMIN": ("admin", []),
}


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        app.state.container.__dict__["user_service"] = UserService(sessions, erp_sync=queue)
        yield test_client


async def _setup(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> tuple[int, dict[str, str]]:
    """Админ (вход) и сотрудник-менеджер без ролей Платформы."""
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    return employee.id, login(client, admin.email, password)


async def _row(sessions: async_sessionmaker[AsyncSession], user_id: int) -> User:
    async with sessions() as session:
        row = await session.get(User, user_id)
        assert row is not None
        return row


async def _roles(sessions: async_sessionmaker[AsyncSession], user_id: int) -> list[str]:
    async with sessions() as session:
        return await repo.roles_of(session, user_id)


async def _audit(sessions: async_sessionmaker[AsyncSession], action: str) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        )
        return list(rows)


async def test_defaults_are_empty_roles_and_no_position(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await _setup(client, sessions)

    listed = {u["email"]: u for u in client.get("/api/v1/users", headers=boss).json()}
    assert listed["dilshod@railtech.uz"]["platform_roles"] == []
    assert listed["dilshod@railtech.uz"]["position"] is None
    me = client.get("/api/v1/me", headers=boss).json()
    assert (me["platform_roles"], me["position"]) == ([], None)
    assert client.get(f"/api/v1/users/{employee}", headers=boss).json()["platform_roles"] == []


@pytest.mark.parametrize(("code", "expected"), list(TABLE.items()))
async def test_every_platform_role_computes_crm_role_access_and_erp_roles(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    queue: Queue,
    code: str,
    expected: tuple[str, list[str]],
) -> None:
    crm_role, role_codes = expected
    employee, boss = await _setup(client, sessions)

    response = client.patch(
        f"/api/v1/users/{employee}", json={"platform_roles": [code]}, headers=boss
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platform_roles"] == [code]
    assert body["roles"] == [crm_role]
    assert body["platform_access"] == ["crm", "erp"]
    assert body["erp_role_codes"] == role_codes
    assert await _roles(sessions, employee) == [crm_role]
    row = await _row(sessions, employee)
    assert (row.platform_roles, row.platform_access) == ([code], ["crm", "erp"])
    assert row.ui_mode == "manager"  # переключатель Админ/Менеджер — выбор самого админа
    assert queue.jobs == [("provision", employee)]  # доступ выдан ролью -> провижининг
    assert client.get("/api/v1/users", headers=boss).json()[-1]["platform_roles"] == [code]


async def test_two_roles_are_united_and_the_senior_crm_role_wins(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)

    response = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["ACCOUNTANT", "DIRECTOR", "ACCOUNTANT"]},
        headers=boss,
    )

    body = response.json()
    assert body["platform_roles"] == ["DIRECTOR", "ACCOUNTANT"]  # без дублей, порядок контракта
    assert body["roles"] == ["manager"]  # manager > viewer
    assert body["erp_role_codes"] == ["FINANCE", "HEAD"]
    assert queue.jobs == [("provision", employee)]

    queue.jobs.clear()
    again = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["ACCOUNTANT", "DIRECTOR"]},
        headers=boss,
    )
    assert again.status_code == 200
    assert queue.jobs == [], "тот же набор — ничего не меняется"


async def test_admin_role_outranks_the_others(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await _setup(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["SUPPLY", "ADMIN"]},
        headers=boss,
    ).json()

    assert body["roles"] == ["admin"]
    assert body["erp_role_codes"] == ["CATALOG_SUPPLY", "FULFILLMENT"]


async def test_manual_roles_in_the_same_request_are_overridden(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await _setup(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={
            "platform_roles": ["DIRECTOR"],
            "roles": ["admin"],
            "platform_access": ["crm"],
            "erp_role_codes": ["FINANCE"],
        },
        headers=boss,
    ).json()

    assert (body["roles"], body["platform_access"], body["erp_role_codes"]) == (
        ["viewer"],
        ["crm", "erp"],
        ["HEAD"],
    )
    # Ручная правка ролей пользователя, которым управляют роли Платформы, тоже не действует.
    manual = client.patch(
        f"/api/v1/users/{employee}", json={"roles": ["admin"], "erp_role_codes": []}, headers=boss
    ).json()
    assert (manual["roles"], manual["erp_role_codes"]) == (["viewer"], ["HEAD"])


async def test_removing_all_roles_drops_the_derived_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["MANAGER", "ACCOUNTANT"]},
        headers=boss,
    )
    queue.jobs.clear()

    response = client.patch(f"/api/v1/users/{employee}", json={"platform_roles": []}, headers=boss)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platform_roles"] == []
    assert (body["roles"], body["platform_access"], body["erp_role_codes"]) == (
        ["viewer"],
        ["crm"],
        [],
    )
    assert queue.jobs == [("revoke", employee)]  # доступ к ERP снят вместе с ролями
    actions = [e.action for e in await _audit(sessions, "platform_access.revoked")]
    assert actions == ["platform_access.revoked"]


async def test_removing_roles_with_manual_values_keeps_them(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)
    client.patch(f"/api/v1/users/{employee}", json={"platform_roles": ["DIRECTOR"]}, headers=boss)
    queue.jobs.clear()

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={
            "platform_roles": [],
            "roles": ["manager"],
            "platform_access": ["crm", "erp"],
            "erp_role_codes": ["FINANCE"],
        },
        headers=boss,
    ).json()

    assert (body["roles"], body["platform_access"], body["erp_role_codes"]) == (
        ["manager"],
        ["crm", "erp"],
        ["FINANCE"],
    )
    assert queue.jobs == [("provision", employee)]
    # Дальше — прежнее поведение: роли и роли ERP ведутся вручную.
    manual = client.patch(
        f"/api/v1/users/{employee}", json={"roles": ["viewer"], "erp_role_codes": []}, headers=boss
    ).json()
    assert (manual["roles"], manual["erp_role_codes"]) == (["viewer"], [])


async def test_empty_platform_roles_keep_the_old_manual_behaviour(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={"roles": ["viewer"], "platform_access": ["crm", "erp"], "erp_role_codes": ["HEAD"]},
        headers=boss,
    ).json()

    assert (body["roles"], body["erp_role_codes"], body["platform_roles"]) == (
        ["viewer"],
        ["HEAD"],
        [],
    )
    assert queue.jobs == [("provision", employee)]


async def test_roles_change_is_audited_with_before_and_after(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Аудит `user.update`: роли Платформы и вычисленные роли CRM — до и после."""
    employee, boss = await _setup(client, sessions)
    client.patch(f"/api/v1/users/{employee}", json={"platform_roles": ["SUPPLY"]}, headers=boss)
    client.patch(f"/api/v1/users/{employee}", json={"platform_roles": []}, headers=boss)

    updates = [e for e in await _audit(sessions, "user.update") if e.entity_id == str(employee)]
    granted, removed = updates
    assert granted.before is not None
    assert granted.after is not None
    assert (granted.before["platform_roles"], granted.before["roles"]) == ([], ["manager"])
    assert (granted.after["platform_roles"], granted.after["roles"]) == (["SUPPLY"], ["viewer"])
    assert granted.after["erp_role_codes"] == ["CATALOG_SUPPLY", "FULFILLMENT"]
    assert granted.after["platform_access"] == ["crm", "erp"]
    assert removed.before is not None
    assert removed.after is not None
    assert removed.before["platform_roles"] == ["SUPPLY"]
    assert (removed.after["platform_roles"], removed.after["platform_access"]) == ([], ["crm"])
    assert granted.actor_user_id is not None


async def test_unrelated_update_does_not_audit_roles_or_touch_erp(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)
    client.patch(f"/api/v1/users/{employee}", json={"platform_roles": ["ENGINEER"]}, headers=boss)
    queue.jobs.clear()

    response = client.patch(f"/api/v1/users/{employee}", json={"tg_user_id": 777}, headers=boss)

    assert response.status_code == 200
    assert response.json()["roles"] == ["viewer"]
    assert queue.jobs == []
    updates = [e for e in await _audit(sessions, "user.update") if e.entity_id == str(employee)]
    assert len(updates) == 2
    assert updates[0].after is not None
    assert updates[1].after is not None
    assert updates[1].after["roles"] == updates[0].after["roles"] == ["viewer"]


async def test_position_is_saved_trimmed_cleared_and_limited(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await _setup(client, sessions)

    saved = client.patch(
        f"/api/v1/users/{employee}", json={"position": "  Главный инженер  "}, headers=boss
    )
    assert saved.json()["position"] == "Главный инженер"
    assert (await _row(sessions, employee)).position == "Главный инженер"
    assert queue.jobs == [], "должность не касается ERP"

    assert (
        client.patch(f"/api/v1/users/{employee}", json={"tg_user_id": 5}, headers=boss).json()[
            "position"
        ]
        == "Главный инженер"
    )
    assert (
        client.patch(
            f"/api/v1/users/{employee}", json={"position": "я" * 120}, headers=boss
        ).status_code
        == 200
    )
    too_long = client.patch(f"/api/v1/users/{employee}", json={"position": "я" * 121}, headers=boss)
    assert too_long.status_code == 422
    cleared = client.patch(f"/api/v1/users/{employee}", json={"position": ""}, headers=boss)
    assert cleared.json()["position"] is None
    assert (await _row(sessions, employee)).position is None


@pytest.mark.parametrize("value", [["ROOT"], ["manager"], ["MANAGER", "admin"], "MANAGER", [1]])
async def test_foreign_platform_role_is_rejected(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    queue: Queue,
    value: object,
) -> None:
    employee, boss = await _setup(client, sessions)

    response = client.patch(
        f"/api/v1/users/{employee}", json={"platform_roles": value}, headers=boss
    )

    assert response.status_code == 422
    assert queue.jobs == []
    assert (await _row(sessions, employee)).platform_roles == []


async def test_only_admin_changes_platform_roles_and_position(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    mine = login(client, manager.email, password)

    for body in ({"platform_roles": ["ADMIN"]}, {"position": "Директор"}):
        response = client.patch(f"/api/v1/users/{manager.id}", json=body, headers=mine)
        assert response.status_code == 403
    created = client.post(
        "/api/v1/users",
        json={"email": "new@railtech.uz", "full_name": "Новый", "platform_roles": ["ADMIN"]},
        headers=mine,
    )
    assert created.status_code == 403
    assert client.get("/api/v1/me", headers=mine).json()["platform_roles"] == []
    assert queue.jobs == []


async def test_last_active_admin_cannot_lose_the_admin_role_by_platform_roles(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)
    client.patch(f"/api/v1/users/{admin.id}", json={"platform_roles": ["ADMIN"]}, headers=boss)
    queue.jobs.clear()

    demotions: list[list[str]] = [["DIRECTOR"], []]
    for roles in demotions:
        response = client.patch(
            f"/api/v1/users/{admin.id}", json={"platform_roles": roles}, headers=boss
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "last_admin"

    assert await _roles(sessions, admin.id) == ["admin"]
    assert (await _row(sessions, admin.id)).platform_roles == ["ADMIN"]
    assert queue.jobs == []
    # Роль сохраняется, если ADMIN остаётся среди ролей.
    still = client.patch(
        f"/api/v1/users/{admin.id}", json={"platform_roles": ["ADMIN", "DIRECTOR"]}, headers=boss
    )
    assert still.status_code == 200
    assert still.json()["roles"] == ["admin"]


async def test_second_admin_makes_the_demotion_possible(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    other, _ = await make_user(sessions, "second@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    client.patch(f"/api/v1/users/{other.id}", json={"platform_roles": ["ADMIN"]}, headers=boss)

    demoted = client.patch(
        f"/api/v1/users/{admin.id}", json={"platform_roles": ["DIRECTOR"]}, headers=boss
    )

    assert demoted.status_code == 200
    assert demoted.json()["roles"] == ["viewer"]
    # Теперь админ один — другой, и его снять нельзя.
    blocked = client.patch(
        f"/api/v1/users/{other.id}",
        json={"platform_roles": []},
        headers=login(client, "second@railtech.uz", PASSWORD),
    )
    assert blocked.status_code == 409


async def test_create_with_platform_roles_computes_access_and_queues_provisioning(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    _, boss = await _setup(client, sessions)

    response = client.post(
        "/api/v1/users",
        json={
            "email": "Supply@railtech.uz",
            "full_name": "Снабженец",
            "platform_roles": ["SUPPLY", "ENGINEER"],
            "position": "Начальник отдела закупок",
        },
        headers=boss,
    )

    assert response.status_code == 201, response.text
    user = response.json()["user"]
    assert response.json()["temporary_password"]
    assert user["roles"] == ["viewer"]
    assert user["platform_roles"] == ["SUPPLY", "ENGINEER"]
    assert user["position"] == "Начальник отдела закупок"
    assert (user["platform_access"], user["erp_role_codes"]) == (
        ["crm", "erp"],
        ["CATALOG_SUPPLY", "FULFILLMENT"],
    )
    assert queue.jobs == [("provision", user["id"])]
    granted = await _audit(sessions, "platform_access.granted")
    assert [e.entity_id for e in granted] == [str(user["id"])]


async def test_create_without_platform_roles_still_needs_crm_roles(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    _, boss = await _setup(client, sessions)

    nothing = client.post(
        "/api/v1/users", json={"email": "a@railtech.uz", "full_name": "А"}, headers=boss
    )
    assert nothing.status_code == 422

    old = client.post(
        "/api/v1/users",
        json={"email": "b@railtech.uz", "full_name": "Б", "roles": ["manager"]},
        headers=boss,
    )
    assert old.status_code == 201
    assert old.json()["user"]["platform_roles"] == []
    assert old.json()["user"]["platform_access"] == ["crm"]
    assert queue.jobs == []


async def test_first_admin_from_setup_gets_the_admin_platform_role(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> None:
    app = create_app(live_settings)
    with TestClient(app) as client:
        app.state.container.__dict__["user_service"] = UserService(sessions, erp_sync=queue)
        app.state.container.__dict__.pop("setup_service", None)
        gate = app.state.container.setup_service._gate
        gate.issue(app.state.container.setup_service._clock())
        response = client.post(
            "/api/v1/setup/admin",
            json={
                "code": gate.code,
                "email": "owner@railtech.uz",
                "full_name": "Владелец",
                "password": "Sup3rSecretPass",
            },
        )
        assert response.status_code == 200, response.text
        me = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
        ).json()

    assert me["platform_roles"] == ["ADMIN"]
    assert (me["roles"], me["platform_access"], me["erp_role_codes"]) == (
        ["admin"],
        ["crm", "erp"],
        [],
    )
    assert queue.jobs == [("provision", me["id"])]
