"""Роли Платформы как данные (R-1, ADR-0012) на настоящем Postgres: выдача роли сотруднику.

Роли выдаются `PATCH/POST /users` с `platform_role_ids` (или старыми кодами `platform_roles` —
совместимость BFF до R-2). Роли вычисляют роль CRM (старый фронт), доступ к ERP и очередь
провижининга; права ERP считает провижининг из матриц ролей, `erp_role_codes` пусты.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user
from tests.integration.roles_helpers import (
    audit_rows,
    crm_roles,
    defer_erp_job,
    legacy_ids,
    make_client,
    role_ids,
    setup_staff,
    user_row,
)
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration

# Старый код роли -> базовая роль CRM для старого фронта (как до R-1).
BASE_ROLE = {
    "MANAGER": "manager",
    "DIRECTOR": "viewer",
    "SUPPLY": "viewer",
    "ENGINEER": "viewer",
    "ACCOUNTANT": "manager",
    "ADMIN": "admin",
}


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> Iterator[TestClient]:
    yield from make_client(sessions, live_settings, queue)


async def test_defaults_are_empty_roles_and_no_position(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)

    listed = {u["email"]: u for u in client.get("/api/v1/users", headers=boss).json()}
    card = listed["dilshod@railtech.uz"]
    assert (card["platform_roles"], card["platform_role_ids"], card["platform_role_refs"]) == (
        [],
        [],
        [],
    )
    assert (card["position"], card["erp_sync"], card["erp_sync_error"]) == (
        None,
        "not_applicable",
        None,
    )
    me = client.get("/api/v1/me", headers=boss).json()
    assert (me["platform_roles"], me["platform_role_ids"], me["position"]) == ([], [], None)
    assert client.get(f"/api/v1/users/{employee}", headers=boss).json()["platform_roles"] == []


@pytest.mark.parametrize("code", list(BASE_ROLE))
async def test_every_catalog_role_by_id_computes_crm_role_access_and_queues_provisioning(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    queue: Queue,
    code: str,
) -> None:
    employee, boss = await setup_staff(client, sessions)
    (role_id,) = legacy_ids(client, boss, [code])

    response = client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": [role_id]}, headers=boss
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platform_role_ids"] == [role_id]
    assert [r["id"] for r in body["platform_role_refs"]] == [role_id]
    assert body["platform_roles"] == [code]  # старое поле для BFF до R-2
    assert body["roles"] == [BASE_ROLE[code]]
    assert body["platform_access"] == ["crm", "erp"]
    assert body["erp_role_codes"] == []  # права ERP — вычисленный набор, не системные роли
    assert body["erp_sync"] == "pending"
    assert await crm_roles(sessions, employee) == [BASE_ROLE[code]]
    assert (await user_row(sessions, employee)).ui_mode == "manager"
    assert queue.jobs == [("provision", employee)]  # доступ выдан ролью -> провижининг
    ref = body["platform_role_refs"][0]
    assert ref["system"] is (code in ("ADMIN", "DIRECTOR"))
    assert ref["code"] == (code if ref["system"] else f"tpl:{code}")


async def test_old_codes_are_still_accepted_and_resolve_to_the_same_roles(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    """Совместимость BFF до R-2: `platform_roles` (коды) на входе = роли из шаблонов и системные."""
    employee, boss = await setup_staff(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["ACCOUNTANT", "DIRECTOR", "ACCOUNTANT"]},
        headers=boss,
    ).json()

    assert body["platform_roles"] == ["DIRECTOR", "ACCOUNTANT"]  # без дублей, прежний порядок
    assert sorted(body["platform_role_ids"]) == sorted(
        legacy_ids(client, boss, ["DIRECTOR", "ACCOUNTANT"])
    )
    assert body["roles"] == ["manager"]  # manager > viewer
    assert body["erp_role_codes"] == []
    assert queue.jobs == [("provision", employee)]

    queue.jobs.clear()
    again = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_roles": ["ACCOUNTANT", "DIRECTOR"]},
        headers=boss,
    )
    assert again.status_code == 200
    assert queue.jobs == [], "тот же набор — ничего не меняется"


async def test_two_roles_by_id_are_united_and_a_custom_role_has_no_legacy_code(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)
    custom = client.post(
        "/api/v1/platform-roles",
        json={"name": "Менеджер и бухгалтер", "access": {"crm.leads": "full"}},
        headers=boss,
    ).json()
    (manager_id,) = legacy_ids(client, boss, ["MANAGER"])

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": [custom["id"], manager_id]},
        headers=boss,
    ).json()

    assert body["platform_role_ids"] == sorted([custom["id"], manager_id])
    assert body["platform_roles"] == ["MANAGER"]  # у роли без кода старого значения нет
    assert body["roles"] == ["manager"]  # crm.leads full -> manager


async def test_admin_role_outranks_the_others(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": legacy_ids(client, boss, ["SUPPLY", "ADMIN"])},
        headers=boss,
    ).json()

    assert body["roles"] == ["admin"]
    assert body["erp_role_codes"] == []


async def test_manual_roles_in_the_same_request_are_overridden(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={
            "platform_role_ids": legacy_ids(client, boss, ["DIRECTOR"]),
            "roles": ["admin"],
            "platform_access": ["crm"],
            "erp_role_codes": ["FINANCE"],
        },
        headers=boss,
    ).json()

    assert (body["roles"], body["platform_access"], body["erp_role_codes"]) == (
        ["viewer"],
        ["crm", "erp"],
        [],
    )
    # Ручная правка ролей пользователя, которым управляют роли Платформы, тоже не действует.
    manual = client.patch(
        f"/api/v1/users/{employee}",
        json={"roles": ["admin"], "erp_role_codes": ["HEAD"]},
        headers=boss,
    ).json()
    assert (manual["roles"], manual["erp_role_codes"]) == (["viewer"], [])


async def test_removing_all_roles_drops_the_derived_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": legacy_ids(client, boss, ["MANAGER", "ACCOUNTANT"])},
        headers=boss,
    )
    queue.jobs.clear()

    response = client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": []}, headers=boss
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["platform_roles"], body["platform_role_ids"]) == ([], [])
    assert (body["roles"], body["platform_access"], body["erp_role_codes"]) == (
        ["viewer"],
        ["crm"],
        [],
    )
    assert queue.jobs == [("revoke", employee)]  # доступ к ERP снят вместе с ролями
    assert [e.action for e in await audit_rows(sessions, "platform_access.revoked")] == [
        "platform_access.revoked"
    ]


async def test_removing_roles_with_manual_values_keeps_them(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": legacy_ids(client, boss, ["SUPPLY"])},
        headers=boss,
    )
    queue.jobs.clear()

    body = client.patch(
        f"/api/v1/users/{employee}",
        json={
            "platform_role_ids": [],
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
    employee, boss = await setup_staff(client, sessions)

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
    """Аудит `user.update`: роли Платформы (id и названия) и вычисленные роли CRM — до и после."""
    employee, boss = await setup_staff(client, sessions)
    (supply,) = legacy_ids(client, boss, ["SUPPLY"])
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": [supply]}, headers=boss)
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": []}, headers=boss)

    updates = [e for e in await audit_rows(sessions, "user.update") if e.entity_id == str(employee)]
    granted, removed = updates
    assert granted.before is not None
    assert granted.after is not None
    assert (granted.before["platform_role_ids"], granted.before["roles"]) == ([], ["manager"])
    assert (granted.after["platform_role_ids"], granted.after["roles"]) == ([supply], ["viewer"])
    assert granted.after["platform_role_names"] == ["Снабженец"]
    assert granted.after["platform_access"] == ["crm", "erp"]
    assert removed.before is not None
    assert removed.after is not None
    assert removed.before["platform_role_ids"] == [supply]
    assert (removed.after["platform_role_ids"], removed.after["platform_access"]) == ([], ["crm"])
    assert granted.actor_user_id is not None


async def test_unrelated_update_does_not_audit_roles_or_touch_erp(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": legacy_ids(client, boss, ["ENGINEER"])},
        headers=boss,
    )
    queue.jobs.clear()

    response = client.patch(f"/api/v1/users/{employee}", json={"tg_user_id": 777}, headers=boss)

    assert response.status_code == 200
    assert response.json()["roles"] == ["viewer"]
    assert queue.jobs == []
    updates = [e for e in await audit_rows(sessions, "user.update") if e.entity_id == str(employee)]
    assert len(updates) == 2
    assert updates[0].after is not None
    assert updates[1].after is not None
    assert updates[1].after["roles"] == updates[0].after["roles"] == ["viewer"]


async def test_position_is_saved_trimmed_cleared_and_limited(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)

    saved = client.patch(
        f"/api/v1/users/{employee}", json={"position": "  Главный инженер  "}, headers=boss
    )
    assert saved.json()["position"] == "Главный инженер"
    assert (await user_row(sessions, employee)).position == "Главный инженер"
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
    assert (await user_row(sessions, employee)).position is None


@pytest.mark.parametrize(
    "body",
    [
        {"platform_roles": ["ROOT"]},
        {"platform_roles": ["manager"]},
        {"platform_roles": ["MANAGER", "admin"]},
        {"platform_roles": "MANAGER"},
        {"platform_roles": [1]},
        {"platform_role_ids": [9999]},
        {"platform_role_ids": [0]},
        {"platform_role_ids": ["x"]},
        {"platform_role_ids": [1], "platform_roles": ["MANAGER"]},
    ],
)
async def test_foreign_platform_role_is_rejected(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    queue: Queue,
    body: dict[str, object],
) -> None:
    employee, boss = await setup_staff(client, sessions)

    response = client.patch(f"/api/v1/users/{employee}", json=body, headers=boss)

    assert response.status_code == 422, response.text
    assert queue.jobs == []
    assert client.get(f"/api/v1/users/{employee}", headers=boss).json()["platform_role_ids"] == []


async def test_only_admin_changes_platform_roles_and_position(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    mine = login(client, manager.email, password)

    for body in (
        {"platform_role_ids": [1]},
        {"platform_roles": ["ADMIN"]},
        {"position": "Директор"},
    ):
        response = client.patch(f"/api/v1/users/{manager.id}", json=body, headers=mine)
        assert response.status_code == 403
    created = client.post(
        "/api/v1/users",
        json={"email": "new@railtech.uz", "full_name": "Новый", "platform_role_ids": [1]},
        headers=mine,
    )
    assert created.status_code == 403
    assert client.get("/api/v1/me", headers=mine).json()["platform_roles"] == []
    assert queue.jobs == []


async def test_last_active_admin_cannot_lose_the_admin_role(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)
    (admin_role, director_role) = legacy_ids(client, boss, ["ADMIN", "DIRECTOR"])
    client.patch(
        f"/api/v1/users/{admin.id}", json={"platform_role_ids": [admin_role]}, headers=boss
    )
    queue.jobs.clear()

    demotions: list[list[int]] = [[director_role], []]
    for roles in demotions:
        response = client.patch(
            f"/api/v1/users/{admin.id}", json={"platform_role_ids": roles}, headers=boss
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "last_admin"
    deactivation = client.patch(
        f"/api/v1/users/{admin.id}", json={"is_active": False}, headers=boss
    )
    assert (deactivation.status_code, deactivation.json()["code"]) == (409, "last_admin")

    assert await crm_roles(sessions, admin.id) == ["admin"]
    assert client.get(f"/api/v1/users/{admin.id}", headers=boss).json()["platform_role_ids"] == [
        admin_role
    ]
    assert queue.jobs == []
    # Роль сохраняется, если ADMIN остаётся среди ролей.
    still = client.patch(
        f"/api/v1/users/{admin.id}",
        json={"platform_role_ids": [admin_role, director_role]},
        headers=boss,
    )
    assert still.status_code == 200
    assert still.json()["roles"] == ["admin"]


async def test_second_admin_makes_the_demotion_possible(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    other, _ = await make_user(sessions, "second@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    admin_role, director_role = legacy_ids(client, boss, ["ADMIN", "DIRECTOR"])
    client.patch(
        f"/api/v1/users/{other.id}", json={"platform_role_ids": [admin_role]}, headers=boss
    )

    demoted = client.patch(
        f"/api/v1/users/{admin.id}", json={"platform_role_ids": [director_role]}, headers=boss
    )

    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["roles"] == ["viewer"]
    # Теперь админ один — другой, и его снять нельзя.
    blocked = client.patch(
        f"/api/v1/users/{other.id}",
        json={"platform_role_ids": []},
        headers=login(client, "second@railtech.uz", PASSWORD),
    )
    assert blocked.status_code == 409


async def test_last_active_director_cannot_lose_the_role_or_be_deactivated(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    second, _ = await make_user(sessions, "second@railtech.uz", ["viewer"])
    (director,) = legacy_ids(client, boss, ["DIRECTOR"])
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": [director]}, headers=boss)

    bodies: list[dict[str, object]] = [{"platform_role_ids": []}, {"is_active": False}]
    for body in bodies:
        blocked = client.patch(f"/api/v1/users/{employee}", json=body, headers=boss)
        assert (blocked.status_code, blocked.json()["code"]) == (409, "last_director"), body
    assert client.get(f"/api/v1/users/{employee}", headers=boss).json()["platform_role_ids"] == [
        director
    ]

    # Второй директор снимает ограничение: первого можно лишить роли и отключить.
    client.patch(f"/api/v1/users/{second.id}", json={"platform_role_ids": [director]}, headers=boss)
    assert (
        client.patch(
            f"/api/v1/users/{employee}", json={"platform_role_ids": []}, headers=boss
        ).status_code
        == 200
    )
    # Роль не пропала: теперь последний — второй, и ему нельзя.
    last = client.patch(f"/api/v1/users/{second.id}", json={"is_active": False}, headers=boss)
    assert (last.status_code, last.json()["code"]) == (409, "last_director")


async def test_a_company_without_directors_can_still_manage_users(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Директора ещё нет (первый запуск): ограничение — только «не лишить последнего»."""
    employee, boss = await setup_staff(client, sessions)

    deactivated = client.patch(f"/api/v1/users/{employee}", json={"is_active": False}, headers=boss)

    assert deactivated.status_code == 200


async def test_create_with_platform_roles_computes_access_and_queues_provisioning(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    _, boss = await setup_staff(client, sessions)
    ids = legacy_ids(client, boss, ["SUPPLY", "ENGINEER"])

    response = client.post(
        "/api/v1/users",
        json={
            "email": "Supply@railtech.uz",
            "full_name": "Снабженец",
            "platform_role_ids": ids,
            "position": "Начальник отдела закупок",
        },
        headers=boss,
    )

    assert response.status_code == 201, response.text
    user = response.json()["user"]
    assert response.json()["temporary_password"]
    assert user["roles"] == ["viewer"]
    assert user["platform_roles"] == ["SUPPLY", "ENGINEER"]
    assert user["platform_role_ids"] == sorted(ids)
    assert user["position"] == "Начальник отдела закупок"
    assert (user["platform_access"], user["erp_role_codes"]) == (["crm", "erp"], [])
    assert queue.jobs == [("provision", user["id"])]
    granted = await audit_rows(sessions, "platform_access.granted")
    assert [e.entity_id for e in granted] == [str(user["id"])]


async def test_create_by_old_codes_still_works_and_without_roles_needs_crm_roles(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    _, boss = await setup_staff(client, sessions)

    by_code = client.post(
        "/api/v1/users",
        json={"email": "c@railtech.uz", "full_name": "В", "platform_roles": ["MANAGER"]},
        headers=boss,
    )
    assert by_code.status_code == 201, by_code.text
    assert by_code.json()["user"]["platform_roles"] == ["MANAGER"]
    queue.jobs.clear()

    nothing = client.post(
        "/api/v1/users", json={"email": "a@railtech.uz", "full_name": "А"}, headers=boss
    )
    assert nothing.status_code == 422
    unknown = client.post(
        "/api/v1/users",
        json={"email": "d@railtech.uz", "full_name": "Г", "platform_role_ids": [9999]},
        headers=boss,
    )
    assert unknown.status_code == 422

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
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        me = client.get("/api/v1/me", headers=headers).json()
        roles = role_ids(client, headers)

    assert me["platform_roles"] == ["ADMIN"]
    assert me["platform_role_ids"] == [roles["ADMIN"]]
    assert (me["roles"], me["platform_access"], me["erp_role_codes"]) == (
        ["admin"],
        ["crm", "erp"],
        [],
    )
    assert queue.jobs == [("provision", me["id"])]


async def test_erp_sync_reports_pending_error_ok_and_not_applicable(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)

    def status() -> tuple[str, str | None]:
        card = client.get(f"/api/v1/users/{employee}", headers=boss).json()
        return card["erp_sync"], card["erp_sync_error"]

    assert status() == ("not_applicable", None)
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": legacy_ids(client, boss, ["MANAGER"])},
        headers=boss,
    )
    assert status() == ("ok", None)  # фиктивная очередь ничего не оставила в настоящей

    await defer_erp_job(sessions, employee)
    assert status() == ("pending", None)  # задача стоит в настоящей очереди
    listed = {u["id"]: u for u in client.get("/api/v1/users", headers=boss).json()}
    assert listed[employee]["erp_sync"] == "pending"

    async with sessions() as session, session.begin():
        await session.execute(text("UPDATE procrastinate_jobs SET status = 'succeeded'"))
        await session.execute(
            text("UPDATE users SET erp_sync_error = :e WHERE id = :id"),
            {"e": "erp_provision_user: erp_unavailable: ERP недоступна", "id": employee},
        )
    assert status() == ("error", "erp_provision_user: erp_unavailable: ERP недоступна")
