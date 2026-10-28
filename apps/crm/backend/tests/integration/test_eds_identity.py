"""CRM → EDS (волна 12, E4) на настоящем Postgres: права EDS в `identity.user.*` и токен для EDS.

Права EDS (`user.permissions.eds`) CRM вычисляет из ролей Платформы по каталогу. При любом
изменении, меняющем их, в той же транзакции в outbox уходит `identity.user.updated`, где
`changed_fields` включает `permissions`: назначение и снятие ролей, правка матрицы роли
(каждому держателю, у кого права поменялись), активация. Тем, у кого права не изменились,
события нет.
"""

from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from tests.integration.crm_helpers import login, make_user
from tests.integration.roles_helpers import legacy_ids, make_client, patch_role
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration
SSO_SECRET = "integration-sso-secret-for-tests-only"
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
USER_CREATED = "uz.railtech.identity.user.created.v1"
ACCOUNTANT = [
    "letters.read",
    "memos.create",
    "payments.confirm",
    "registry.export",
    "registry.read",
]
INBOX_READ = ["letters.read", "registry.read"]


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(
        update={
            "platform_sso_enabled": True,
            "platform_sso_secret": SecretStr(SSO_SECRET),
            "erp_frontend_url": "http://erp.localhost",
        }
    )
    yield from make_client(sessions, settings, queue)


async def events(
    sessions: async_sessionmaker[AsyncSession], event_type: str = USER_UPDATED
) -> list[dict[str, Any]]:
    """`data` событий данного типа в порядке записи."""
    async with sessions() as session:
        rows = (
            await session.execute(
                text("SELECT envelope FROM rt_bus_outbox WHERE type = :t ORDER BY created_at, id"),
                {"t": event_type},
            )
        ).scalars()
        return [row["data"] for row in rows]


async def clear_outbox(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM rt_bus_outbox"))


def holders_of(data: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {d["user"]["crm_user_id"]: d for d in data}


def no_eds_role(client: TestClient, boss: dict[str, str]) -> int:
    """Роль без разделов EDS: сотрудника нельзя оставить совсем без ролей (422 `roles_required`)."""
    return custom_role(client, boss, {"crm.clients": "read"}, name="Только клиенты")


def assign(client: TestClient, boss: dict[str, str], user_id: int, role_ids_: list[int]) -> None:
    response = client.patch(
        f"/api/v1/users/{user_id}", json={"platform_role_ids": role_ids_}, headers=boss
    )
    assert response.status_code == 200, response.text


def custom_role(
    client: TestClient,
    boss: dict[str, str],
    access: dict[str, str],
    name: str = "Менеджер и бухгалтер",
) -> int:
    response = client.post(
        "/api/v1/platform-roles",
        json={"name": name, "access": access},
        headers=boss,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


# --- сотрудник: роли и активация ---------------------------------------------------------------


async def test_created_user_carries_the_eds_permissions_of_the_roles(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)
    director, accountant = legacy_ids(client, boss, ["DIRECTOR", "ACCOUNTANT"])
    await clear_outbox(sessions)

    for email, role in (("direktor@railtech.uz", director), ("buxgalter@railtech.uz", accountant)):
        response = client.post(
            "/api/v1/users",
            json={"email": email, "full_name": "Сотрудник", "platform_role_ids": [role]},
            headers=boss,
        )
        assert response.status_code == 201, response.text

    created = await events(sessions, USER_CREATED)
    assert [d["user"]["permissions"]["eds"] for d in created] == [
        sorted(
            [
                "letters.read",
                "letters.register",
                "letters.resolve",
                "memos.create",
                "memos.approve",
                "approvals.decide",
                "registry.read",
            ]
        ),
        ACCOUNTANT,
    ]


async def test_assigning_and_removing_roles_publishes_the_new_eds_permissions(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    manager, accountant = legacy_ids(client, boss, ["MANAGER", "ACCOUNTANT"])
    plain = no_eds_role(client, boss)
    await clear_outbox(sessions)

    assign(client, boss, employee.id, [manager])
    assign(client, boss, employee.id, [manager, accountant])
    assign(client, boss, employee.id, [plain])

    first, second, third = await events(sessions)
    assert first["user"]["permissions"] == {
        "eds": ["letters.read", "memos.create", "registry.read"]
    }
    assert second["user"]["permissions"] == {"eds": ACCOUNTANT}
    assert "payments.confirm" in second["user"]["permissions"]["eds"]
    assert third["user"]["permissions"] == {"eds": []}
    for data in (first, second, third):
        assert data["user"]["crm_user_id"] == employee.id
    # changed_fields перечисляет все реально изменившиеся поля снимка, а не только права EDS.
    assert first["changed_fields"] == ["permissions", "platform_roles", "systems"]
    assert second["changed_fields"] == ["permissions", "platform_roles"]
    assert third["changed_fields"] == ["permissions", "platform_roles"]
    assert second["user"]["platform_roles"] == ["ACCOUNTANT", "MANAGER"]


async def test_repeating_the_same_roles_publishes_nothing(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    (manager,) = legacy_ids(client, boss, ["MANAGER"])
    assign(client, boss, employee.id, [manager])
    await clear_outbox(sessions)

    assign(client, boss, employee.id, [manager])

    assert await events(sessions) == []


async def test_deactivation_and_activation_follow_the_eds_permissions(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    (manager,) = legacy_ids(client, boss, ["MANAGER"])
    assign(client, boss, employee.id, [manager])
    await clear_outbox(sessions)

    off = client.patch(f"/api/v1/users/{employee.id}", json={"is_active": False}, headers=boss)
    on = client.patch(f"/api/v1/users/{employee.id}", json={"is_active": True}, headers=boss)

    assert (off.status_code, on.status_code) == (200, 200)
    assert len(await events(sessions, "uz.railtech.identity.user.deactivated.v1")) == 1
    (activated,) = await events(sessions)
    assert activated["user"]["is_active"] is True
    assert activated["user"]["permissions"] == {
        "eds": ["letters.read", "memos.create", "registry.read"]
    }
    assert activated["changed_fields"] == ["is_active", "permissions"]


# --- роль: правка матрицы ----------------------------------------------------------------------


async def test_role_matrix_change_publishes_to_every_holder_whose_eds_rights_changed(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Правка роли -> `identity.user.updated` с новым `permissions.eds` (runbook §3, E4)."""
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    alone, _ = await make_user(sessions, "alone@railtech.uz", ["manager"])
    with_director, _ = await make_user(sessions, "both@railtech.uz", ["manager"])
    without_role, _ = await make_user(sessions, "norole@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    (director,) = legacy_ids(client, boss, ["DIRECTOR"])
    role = custom_role(client, boss, {"eds.inbox": "read", "chats.internal": "full"})
    assign(client, boss, alone.id, [role])
    assign(client, boss, with_director.id, [role, director])
    await clear_outbox(sessions)

    # D2-4: директор читает счета, но не подтверждает оплату — его права покрывает «Черновики: full»
    changed = patch_role(
        client, boss, role, {"access": {"eds.inbox": "read", "eds.drafts": "full"}}
    )
    assert changed.status_code == 200, changed.text

    data = await events(sessions)
    by_user = holders_of(data)
    assert set(by_user) == {alone.id}, "у держателя директорской роли права EDS не изменились"
    assert len(data) == 1
    event = by_user[alone.id]
    assert event["user"]["permissions"] == {
        "eds": ["approvals.decide", "letters.read", "registry.read"]
    }
    assert event["changed_fields"] == ["permissions"]
    assert without_role.id not in by_user


async def test_role_change_outside_eds_publishes_nothing(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    role = custom_role(client, boss, {"eds.inbox": "read"})
    assign(client, boss, employee.id, [role])
    await clear_outbox(sessions)

    response = patch_role(
        client, boss, role, {"access": {"eds.inbox": "read", "crm.leads": "full"}}
    )
    renamed = patch_role(client, boss, role, {"name": "Входящие и лиды"})

    assert (response.status_code, renamed.status_code) == (200, 200)
    assert await events(sessions) == []


async def test_role_matrix_change_that_removes_eds_access_publishes_empty_permissions(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    first, _ = await make_user(sessions, "first@railtech.uz", ["manager"])
    second, _ = await make_user(sessions, "second@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    role = custom_role(client, boss, {"eds.inbox": "full"})
    assign(client, boss, first.id, [role])
    assign(client, boss, second.id, [role])
    await clear_outbox(sessions)

    response = patch_role(client, boss, role, {"access": {"eds.inbox": "read"}})
    assert response.status_code == 200, response.text
    reduced = holders_of(await events(sessions))
    assert {u: d["user"]["permissions"]["eds"] for u, d in reduced.items()} == {
        first.id: INBOX_READ,
        second.id: INBOX_READ,
    }

    await clear_outbox(sessions)
    patch_role(client, boss, role, {"access": {"crm.clients": "read"}})
    emptied = holders_of(await events(sessions))
    assert {u: d["user"]["permissions"]["eds"] for u, d in emptied.items()} == {
        first.id: [],
        second.id: [],
    }


async def test_inactive_holder_gets_no_event_on_role_change(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    active, _ = await make_user(sessions, "active@railtech.uz", ["manager"])
    gone, _ = await make_user(sessions, "gone@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    role = custom_role(client, boss, {"eds.inbox": "read"})
    assign(client, boss, active.id, [role])
    assign(client, boss, gone.id, [role])
    client.patch(f"/api/v1/users/{gone.id}", json={"is_active": False}, headers=boss)
    await clear_outbox(sessions)

    patch_role(client, boss, role, {"access": {"eds.inbox": "full"}})

    assert set(holders_of(await events(sessions))) == {active.id}


async def test_deleting_a_role_is_only_possible_without_holders_so_no_rights_change(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, password)
    role = custom_role(client, boss, {"eds.inbox": "read"})
    plain = no_eds_role(client, boss)
    assign(client, boss, employee.id, [role])
    await clear_outbox(sessions)

    refused = client.delete(f"/api/v1/platform-roles/{role}", headers=boss)
    assert refused.status_code == 409
    assert await events(sessions) == []

    assign(client, boss, employee.id, [plain])  # права снимает смена роли, и событие уходит там
    (removed,) = await events(sessions)
    assert removed["user"]["permissions"] == {"eds": []}
    assert client.delete(f"/api/v1/platform-roles/{role}", headers=boss).status_code == 204


# --- токен сотрудника для EDS ------------------------------------------------------------------


async def test_eds_token_follows_the_roles_of_the_employee(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    me = login(client, employee.email, password)
    (accountant,) = legacy_ids(client, boss, ["ACCOUNTANT"])
    plain = no_eds_role(client, boss)

    denied = client.post("/api/v1/auth/sso/token", json={"aud": "eds"}, headers=me)
    assert denied.status_code == 403
    assert denied.json()["details"]["reason"] == "eds_access_denied"

    assign(client, boss, employee.id, [accountant])
    issued = client.post("/api/v1/auth/sso/token", json={"aud": "eds"}, headers=me)
    assert issued.status_code == 200, issued.text
    claims = jwt.decode(
        issued.json()["token"], SSO_SECRET, algorithms=["HS256"], audience="eds", issuer="crm"
    )
    assert claims["sub"] == str(employee.id)
    assert claims["permissions"] == ACCOUNTANT
    assert claims["exp"] - claims["iat"] == 60

    assign(client, boss, employee.id, [plain])
    assert client.post("/api/v1/auth/sso/token", json={"aud": "eds"}, headers=me).status_code == 403


async def test_erp_token_still_works_without_a_body(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    employee, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    me = login(client, employee.email, password)
    client.patch(
        f"/api/v1/users/{employee.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )

    for body in (None, {"aud": "erp"}):
        response = client.post("/api/v1/auth/sso/token", json=body, headers=me)
        assert response.status_code == 200, response.text
        claims = jwt.decode(
            response.json()["token"], SSO_SECRET, algorithms=["HS256"], audience="erp", issuer="crm"
        )
        assert claims["aud"] == "erp"

    unknown = client.post("/api/v1/auth/sso/token", json={"aud": "cabinet"}, headers=me)
    assert unknown.status_code == 422
