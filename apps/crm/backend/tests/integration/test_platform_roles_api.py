"""API ролей Платформы `/api/v1/platform-roles` (R-1, ADR-0012) на настоящем Postgres.

Только admin; системные роли неизменны (409 `role_system`); роль с сотрудниками не удаляется
(409 `role_in_use`); неизвестный раздел или уровень вне `levels` — 422; предпросмотр последствий;
правила casbin меняются сразу; изменение роли ставит провижининг ERP каждому затронутому
сотруднику; аудит `platform_role.create|update|delete`.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.platform_roles_generated import ROLE_ACCESS, ROLE_RESTRICTED_FIELDS
from app.integrations.erp_users import ProvisionPayload
from app.security.rbac import Rbac
from app.services.erp_access import ErpAccessService
from tests.integration.crm_helpers import PASSWORD, login, make_user
from tests.integration.roles_helpers import (
    audit_rows,
    crm_roles,
    legacy_ids,
    make_client,
    patch_role,
    role_ids,
    setup_staff,
)
from tests.integration.test_platform_access import Queue

pytestmark = pytest.mark.integration
ROLES = "/api/v1/platform-roles"


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> Iterator[TestClient]:
    yield from make_client(sessions, live_settings, queue)


class FakeErp:
    def __init__(self) -> None:
        self.payloads: list[ProvisionPayload] = []

    async def provision_user(self, payload: ProvisionPayload) -> int:
        self.payloads.append(payload)
        return 1

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        return True


def _create(client: TestClient, boss: dict[str, str], **body: object) -> dict[str, object]:
    payload = {"name": "Менеджер и бухгалтер", **body}
    response = client.post(ROLES, json=payload, headers=boss)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


# --- список и чтение ----------------------------------------------------------------------------


async def test_list_has_system_roles_and_templates_with_employee_counts(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    (manager,) = legacy_ids(client, boss, ["MANAGER"])
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": [manager]}, headers=boss)

    roles = client.get(ROLES, headers=boss).json()

    assert [(r["code"], r["is_system"]) for r in roles] == [
        ("ADMIN", True),
        ("DIRECTOR", True),
        ("tpl:MANAGER", False),
        ("tpl:SUPPLY", False),
        ("tpl:ENGINEER", False),
        ("tpl:ACCOUNTANT", False),
    ]
    assert {r["code"]: r["employees"] for r in roles}["tpl:MANAGER"] == 1
    director = roles[1]
    assert director["name"] == "Директор"
    assert director["access"]["admin"] == "read"
    assert director["restricted_fields"] == ["cost_margin", "supplier_prices"]
    one = client.get(f"{ROLES}/{manager}", headers=boss)
    assert one.status_code == 200
    assert one.json()["employees"] == 1
    assert client.get(f"{ROLES}/9999", headers=boss).status_code == 404


async def test_admin_manages_roles_a_director_only_reads_and_others_have_no_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R-1b: чтение матрицы — `users:read` (директор), изменение — `users:write` (администратор)."""
    employee, boss = await setup_staff(client, sessions)
    (director,) = legacy_ids(client, boss, ["DIRECTOR"])
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": [director]}, headers=boss)
    other, password = await make_user(sessions, "viewer@railtech.uz", ["manager"])
    reads: tuple[tuple[str, str, dict[str, object] | None], ...] = (
        ("GET", ROLES, None),
        ("GET", f"{ROLES}/3", None),
    )
    writes: tuple[tuple[str, str, dict[str, object] | None], ...] = (
        ("POST", ROLES, {"name": "Х"}),
        ("POST", f"{ROLES}/preview", {}),
        ("PATCH", f"{ROLES}/3", {"name": "Х", "version": 1}),
        ("DELETE", f"{ROLES}/3", None),
    )
    reader = login(client, "dilshod@railtech.uz", PASSWORD)
    stranger = login(client, other.email, password)

    for method, path, body in reads:
        assert client.request(method, path, json=body, headers=reader).status_code == 200
        assert client.request(method, path, json=body, headers=stranger).status_code == 403
    for method, path, body in writes:
        for who in (reader, stranger):
            response = client.request(method, path, json=body, headers=who)
            assert response.status_code == 403, (method, path, response.text)
    assert client.get(ROLES).status_code == 401
    assert len(client.get(ROLES, headers=reader).json()) == 6


# --- создание и проверка ввода ------------------------------------------------------------------


async def test_create_role_is_canonical_audited_and_has_casbin_rules(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)

    role = _create(
        client,
        boss,
        description="  Лиды и счета ",
        access={"eds.payments": "full", "crm.leads": "full"},
        restricted_fields=["totals_only", "cost_margin"],
    )

    assert role["code"] is None
    assert (role["is_system"], role["employees"]) == (False, 0)
    assert role["description"] == "Лиды и счета"
    assert list(role["access"]) == ["crm.leads", "eds.payments"]  # type: ignore[call-overload]
    assert role["restricted_fields"] == ["cost_margin", "totals_only"]
    assert role["created_by"] is not None
    (entry,) = await audit_rows(sessions, "platform_role.create")
    assert (entry.entity_type, entry.entity_id, entry.before) == (
        "platform_role",
        str(role["id"]),
        None,
    )
    assert entry.after is not None
    assert entry.after["name"] == "Менеджер и бухгалтер"
    assert entry.after["access"] == role["access"]
    async with sessions() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM casbin_rule WHERE v0 = :s"), {"s": f"pr:{role['id']}"}
            )
        ).scalar()
    assert rows == len(
        {"leads:read", "leads:take", "leads:work", "leads:reply", "leads:note", "leads:assist",
         "leads:create", "stream:read", "dashboard:read", "kb:read", "reply_templates:read"}
    )  # fmt: skip


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"access": {"crm.nothing": "full"}}, "access"),
        ({"access": {"crm.leads": "hidden"}}, "access"),
        ({"access": {"crm.leads": "write"}}, "access"),
        ({"access": {"erp.calc.goods": "read"}}, "access"),  # у раздела только full
        ({"restricted_fields": ["secret_notes"]}, "restricted_fields"),
        ({"name": "  "}, "name"),
        ({"name": "я" * 121}, "name"),
    ],
)
async def test_create_rejects_unknown_sections_levels_fields_and_names(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    body: dict[str, object],
    field: str,
) -> None:
    _, boss = await setup_staff(client, sessions)

    response = client.post(ROLES, json={"name": "Новая", **body}, headers=boss)

    assert response.status_code == 422, response.text
    assert response.json()["details"]["field"] == field
    assert len(client.get(ROLES, headers=boss).json()) == 6


async def test_role_names_are_unique_ignoring_case(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    _create(client, boss, name="Оператор")

    for name in ("оператор", "ОПЕРАТОР ", "менеджер"):  # и шаблон «Менеджер»
        response = client.post(ROLES, json={"name": name}, headers=boss)
        assert (response.status_code, response.json()["details"]["field"]) == (409, "name")


# --- системные роли и удаление ------------------------------------------------------------------


@pytest.mark.parametrize("code", ["ADMIN", "DIRECTOR"])
async def test_system_roles_cannot_be_changed_or_deleted(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], code: str
) -> None:
    _, boss = await setup_staff(client, sessions)
    (role_id,) = legacy_ids(client, boss, [code])
    before = client.get(f"{ROLES}/{role_id}", headers=boss).json()

    for method, body in (
        ("PATCH", {"name": "Другая", "version": 1}),
        ("PATCH", {"access": {}, "version": 1}),
        ("DELETE", None),
    ):
        response = client.request(method, f"{ROLES}/{role_id}", json=body, headers=boss)
        assert (response.status_code, response.json()["code"]) == (409, "role_system")
    preview = client.post(f"{ROLES}/preview", json={"role_id": role_id, "access": {}}, headers=boss)
    assert (preview.status_code, preview.json()["code"]) == (409, "role_system")

    assert client.get(f"{ROLES}/{role_id}", headers=boss).json() == before
    assert await audit_rows(sessions, "platform_role.update") == []
    assert await audit_rows(sessions, "platform_role.delete") == []


async def test_role_with_employees_cannot_be_deleted_and_a_free_one_can(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.leads": "full"})
    free = _create(client, boss, name="Свободная", access={"crm.clients": "read"})
    client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )

    blocked = client.delete(f"{ROLES}/{role['id']}", headers=boss)

    assert (blocked.status_code, blocked.json()["code"]) == (409, "role_in_use")
    assert blocked.json()["details"]["users"] == 1
    assert client.get(f"{ROLES}/{role['id']}", headers=boss).status_code == 200

    removed = client.delete(f"{ROLES}/{free['id']}", headers=boss)
    assert removed.status_code == 204
    assert client.get(f"{ROLES}/{free['id']}", headers=boss).status_code == 404
    (entry,) = await audit_rows(sessions, "platform_role.delete")
    assert entry.entity_id == str(free["id"])
    assert entry.before is not None
    assert entry.before["access"] == {"crm.clients": "read"}
    assert entry.after is None
    async with sessions() as session:
        left = (
            await session.execute(
                text("SELECT count(*) FROM casbin_rule WHERE v0 = :s"), {"s": f"pr:{free['id']}"}
            )
        ).scalar()
    assert left == 0

    # После снятия роли с сотрудника её можно удалить.
    client.patch(f"/api/v1/users/{employee}", json={"platform_role_ids": []}, headers=boss)
    assert client.delete(f"{ROLES}/{role['id']}", headers=boss).status_code == 204


async def test_delete_unknown_role_is_404(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    assert client.delete(f"{ROLES}/9999", headers=boss).status_code == 404
    missing = patch_role(client, boss, 9999, {"name": "Х"})
    assert missing.status_code == 404


# --- изменение роли -----------------------------------------------------------------------------


async def test_update_changes_casbin_rights_at_once_without_restart(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"})
    who, password = await make_user(sessions, "who@railtech.uz", ["viewer"])
    client.patch(f"/api/v1/users/{who.id}", json={"platform_role_ids": [role["id"]]}, headers=boss)
    mine = login(client, who.email, password)
    assert client.get("/api/v1/users", headers=mine).status_code == 403

    # Роль получает Admin · чтение: сотрудников читать можно, менять — нет.
    patch_role(client, boss, role["id"], {"access": {"admin": "read"}})
    assert client.get("/api/v1/users", headers=mine).status_code == 200
    assert client.get(ROLES, headers=mine).status_code == 200  # R-1b: матрицу читает `users:read`
    assert patch_role(client, mine, role["id"], {"name": "Х"}).status_code == 403
    permissions = client.get("/api/v1/me/permissions", headers=mine).json()["permissions"]
    assert permissions["users"] == {"read": True, "write": False}
    assert permissions["audit"] == {"read": True}

    # Раздел снят: право пропадает сразу.
    patch_role(client, boss, role["id"], {"access": {"crm.leads": "read"}})
    assert client.get("/api/v1/users", headers=mine).status_code == 403
    assert client.get("/api/v1/me/permissions", headers=mine).json()["permissions"]["leads"]["read"]
    assert employee  # сотрудник из setup_staff не затронут


async def test_update_audits_before_and_after_and_keeps_unsent_fields(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"}, restricted_fields=["cost_margin"])

    updated = patch_role(
        client,
        boss,
        role["id"],
        {"name": "  Продажи ", "access": {"crm.clients": "full", "crm.leads": "read"}},
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["name"], body["description"]) == ("Продажи", "")
    assert body["restricted_fields"] == ["cost_margin"]  # не присланное не меняется
    assert body["access"] == {"crm.leads": "read", "crm.clients": "full"}
    assert body["updated_by"] is not None
    (entry,) = await audit_rows(sessions, "platform_role.update")
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before["name"] == "Менеджер и бухгалтер"
    assert entry.after["name"] == "Продажи"
    assert entry.before["access"] == {"crm.clients": "read"}
    assert entry.after["access"] == {"crm.leads": "read", "crm.clients": "full"}

    noop = patch_role(client, boss, role["id"], {"name": "Продажи"})
    assert noop.status_code == 200
    assert (
        len(await audit_rows(sessions, "platform_role.update")) == 1
    )  # без изменений — без записи


async def test_version_grows_on_each_change_and_a_stale_patch_is_a_conflict(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R-1b: `version` растёт при каждом изменении; PATCH с устаревшей версией — 409."""
    _, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"})
    assert role["version"] == 1
    assert {r["version"] for r in client.get(ROLES, headers=boss).json()} <= {1, 2}

    first = patch_role(client, boss, role["id"], {"name": "Продажи"}, version=1)
    assert (first.status_code, first.json()["version"]) == (200, 2)
    second = patch_role(client, boss, role["id"], {"access": {"crm.leads": "read"}}, version=2)
    assert (second.status_code, second.json()["version"]) == (200, 3)

    stale = patch_role(client, boss, role["id"], {"name": "Чужое"}, version=2)
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "role_version_conflict"
    assert stale.json()["details"]["current"] == 3
    current = client.get(f"{ROLES}/{role['id']}", headers=boss).json()
    assert (current["name"], current["version"]) == ("Продажи", 3)  # устаревший запрос не применён

    same = patch_role(client, boss, role["id"], {"name": "Продажи"}, version=3)
    assert (same.status_code, same.json()["version"]) == (200, 3)  # без изменений — версия прежняя


async def test_patch_without_a_version_is_rejected(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    role = _create(client, boss)

    for body in ({"name": "Х"}, {"name": "Х", "version": 0}, {"name": "Х", "version": None}):
        response = client.patch(f"{ROLES}/{role['id']}", json=body, headers=boss)
        assert response.status_code == 422, (body, response.text)


async def test_the_second_of_two_admins_editing_the_same_role_gets_the_conflict(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    other, password = await make_user(sessions, "second-admin@railtech.uz", ["admin"])
    second = login(client, other.email, password)
    role = _create(client, boss, access={"crm.clients": "read"})
    seen = client.get(f"{ROLES}/{role['id']}", headers=second).json()["version"]

    ok = patch_role(client, boss, role["id"], {"access": {"crm.clients": "full"}})
    late = patch_role(client, second, role["id"], {"access": {"crm.clients": "read"}}, version=seen)

    assert ok.status_code == 200
    assert (late.status_code, late.json()["code"]) == (409, "role_version_conflict")
    assert client.get(f"{ROLES}/{role['id']}", headers=boss).json()["access"] == {
        "crm.clients": "full"
    }


async def test_update_validates_and_does_not_apply_anything_on_error(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"})
    _create(client, boss, name="Другая")

    for body, status in (
        ({"access": {"crm.nothing": "full"}}, 422),
        ({"access": {"erp.calc.goods": "read"}}, 422),
        ({"name": "другая"}, 409),
        ({"name": "Новое", "access": {"admin": "x"}}, 422),
    ):
        response = patch_role(client, boss, role["id"], body)
        assert response.status_code == status, (body, response.text)
    unchanged = client.get(f"{ROLES}/{role['id']}", headers=boss).json()
    assert (unchanged["name"], unchanged["access"]) == (
        "Менеджер и бухгалтер",
        {"crm.clients": "read"},
    )


async def test_role_change_queues_provisioning_for_each_active_holder_with_erp_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    first, boss = await setup_staff(client, sessions)
    second_account, _ = await make_user(sessions, "second@railtech.uz", ["viewer"])
    off_account, _ = await make_user(sessions, "off@railtech.uz", ["viewer"])
    second, off = second_account.id, off_account.id
    role = _create(client, boss, access={"crm.clients": "full"})
    for user in (first, second, off):
        client.patch(
            f"/api/v1/users/{user}", json={"platform_role_ids": [role["id"]]}, headers=boss
        )
    client.patch(f"/api/v1/users/{off}", json={"is_active": False}, headers=boss)
    queue.jobs.clear()

    only_name = patch_role(client, boss, role["id"], {"name": "Другое"})
    assert only_name.status_code == 200
    assert queue.jobs == [], "название не меняет права: пересчёт не нужен"

    patch_role(client, boss, role["id"], {"access": {"eds.payments": "full"}})
    assert sorted(queue.jobs) == [("provision", first), ("provision", second)]
    assert ("provision", off) not in queue.jobs  # отключённому провижининг не нужен

    queue.jobs.clear()
    patch_role(client, boss, role["id"], {"restricted_fields": ["cost_margin"]})
    assert sorted(queue.jobs) == [("provision", first), ("provision", second)]


async def test_provisioning_after_a_role_change_sends_the_recomputed_permissions(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "full"})
    client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )
    erp = FakeErp()
    service = ErpAccessService(sessions, erp)

    await service.provision(employee)
    patch_role(
        client,
        boss,
        role["id"],
        {
            "access": {"eds.payments": "full", "erp.stock": "read"},
            "restricted_fields": ["cost_margin"],
        },
    )
    await service.provision(employee)

    first, second = erp.payloads
    assert (first.role, first.role_codes, first.permissions) == ("backoffice", (), ("deal.manage",))
    assert (second.role, second.role_codes) == ("backoffice", ())
    assert second.permissions == (
        "quote.view_cost_margin",
        "finance.invoice",
        "finance.payment",
        "finance.rates",
        "data.export",
    )


async def test_changing_a_role_recomputes_the_crm_role_of_holders(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"})
    client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )
    assert await crm_roles(sessions, employee) == ["viewer"]

    patch_role(client, boss, role["id"], {"access": {"crm.leads": "full"}})
    assert await crm_roles(sessions, employee) == ["manager"]  # crm.leads full -> manager
    patch_role(client, boss, role["id"], {"access": {"admin": "full"}})
    assert await crm_roles(sessions, employee) == ["admin"]
    changed = [e for e in await audit_rows(sessions, "user.update") if e.entity_id == str(employee)]
    assert changed[-1].before == {"roles": ["manager"]}
    assert changed[-1].after == {"roles": ["admin"]}


async def test_a_role_change_cannot_leave_the_company_without_an_admin(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)
    role = _create(client, boss, access={"admin": "full"})
    client.patch(
        f"/api/v1/users/{admin.id}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )

    blocked = patch_role(client, boss, role["id"], {"access": {"crm.leads": "read"}})

    assert (blocked.status_code, blocked.json()["code"]) == (409, "last_admin")
    assert client.get(f"{ROLES}/{role['id']}", headers=boss).json()["access"] == {"admin": "full"}
    assert await crm_roles(sessions, admin.id) == ["admin"]
    assert await audit_rows(sessions, "platform_role.update") == []  # откат вместе с аудитом
    # Со вторым администратором (не по этой роли) правка проходит.
    other, _ = await make_user(sessions, "second@railtech.uz", ["admin"])
    assert other.id != admin.id
    allowed = patch_role(client, boss, role["id"], {"access": {"crm.leads": "read"}})
    assert allowed.status_code == 200


# --- предпросмотр -------------------------------------------------------------------------------


async def test_preview_lists_who_gains_and_loses_what(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    ids = role_ids(client, boss)
    role = _create(
        client,
        boss,
        access={"crm.leads": "full", "eds.payments": "read"},
        restricted_fields=["cost_margin"],
    )
    client.patch(
        f"/api/v1/users/{employee}",
        json={"platform_role_ids": [role["id"], ids["tpl:ACCOUNTANT"]]},
        headers=boss,
    )

    preview = client.post(
        f"{ROLES}/preview",
        json={
            "role_id": role["id"],
            "access": {"crm.leads": "read", "eds.inbox": "full"},
            "restricted_fields": [],
        },
        headers=boss,
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["role_id"], body["employees_total"]) == (role["id"], 1)
    (impact,) = body["employees"]
    assert impact["user_id"] == employee
    # payments не меняется (бухгалтер даёт full); leads full -> read; inbox read -> full
    assert impact["gained"] == [{"resource": "eds.inbox", "level": "full"}]
    assert impact["lost"] == [{"resource": "crm.leads", "level": "full"}]
    assert (impact["fields_gained"], impact["fields_lost"]) == ([], ["cost_margin"])
    assert impact["erp_gained"] == ["deal.assign"]
    assert impact["erp_lost"] == ["quote.view_cost_margin"]
    assert body["gained"] == impact["gained"]
    assert body["lost"] == impact["lost"]
    assert body["fields_lost"] == ["cost_margin"]
    # Ничего не сохранено.
    saved = client.get(f"{ROLES}/{role['id']}", headers=boss).json()
    assert saved["access"] == {"crm.leads": "full", "eds.payments": "read"}


async def test_preview_without_changes_has_no_affected_employees_and_new_role_has_none(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.leads": "full"})
    client.patch(
        f"/api/v1/users/{employee}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )

    same = client.post(f"{ROLES}/preview", json={"role_id": role["id"]}, headers=boss).json()
    assert (same["employees_total"], same["employees"], same["gained"], same["lost"]) == (
        1,
        [],
        [],
        [],
    )
    draft = client.post(
        f"{ROLES}/preview", json={"access": {"crm.leads": "full"}}, headers=boss
    ).json()
    assert (draft["role_id"], draft["employees_total"], draft["employees"]) == (None, 0, [])


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"role_id": 9999}, 404),
        ({"role_id": 3, "access": {"crm.nothing": "full"}}, 422),
        ({"access": {"erp.calc.goods": "read"}}, 422),
        ({"restricted_fields": ["x"]}, 422),
        ({"role_id": 0}, 422),
    ],
)
async def test_preview_validates_the_draft(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    body: dict[str, object],
    status: int,
) -> None:
    _, boss = await setup_staff(client, sessions)
    assert client.post(f"{ROLES}/preview", json=body, headers=boss).status_code == status


# --- политики и совместимость -------------------------------------------------------------------


async def test_policies_of_roles_created_outside_the_api_are_synced_on_start(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, queue: Queue
) -> None:
    """Роль, появившаяся без API (миграция данных), получает правила casbin при старте CRM."""
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO platform_roles (name, access) "
                "VALUES ('Из миграции', CAST('{\"admin\": \"read\"}' AS jsonb))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3) "
                "VALUES ('p', 'pr:777', 'crm', 'users', 'write')"
            )
        )
        await session.execute(
            text("DELETE FROM casbin_rule WHERE v0 LIKE 'pr:%' AND v0 <> 'pr:777'")
        )
    for test_client in make_client(sessions, live_settings, queue):
        admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
        boss = login(test_client, admin.email, password)
        test_client.get("/api/v1/me/permissions", headers=boss)  # первый запрос создаёт enforcer
        who, who_password = await make_user(sessions, "who@railtech.uz", ["viewer"])
        (new_id,) = [
            r["id"]
            for r in test_client.get(ROLES, headers=boss).json()
            if r["name"] == "Из миграции"
        ]
        test_client.patch(
            f"/api/v1/users/{who.id}", json={"platform_role_ids": [new_id]}, headers=boss
        )
        mine = login(test_client, who.email, who_password)
        assert test_client.get("/api/v1/users", headers=mine).status_code == 200
    async with sessions() as session:
        stale = (
            await session.execute(text("SELECT count(*) FROM casbin_rule WHERE v0 = 'pr:777'"))
        ).scalar()
    assert stale == 0  # правила несуществующей роли убраны


# --- права CRM только из ролей сотрудника -------------------------------------------------------


async def _permissions_of(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], boss: dict[str, str],
    role_id: int, email: str,
) -> dict[str, dict[str, bool]]:  # fmt: skip
    """Сотрудник (базовая роль manager) получает роль; возвращает его `/me/permissions`."""
    account, password = await make_user(sessions, email, ["manager"])
    client.patch(f"/api/v1/users/{account.id}", json={"platform_role_ids": [role_id]}, headers=boss)
    mine = login(client, account.email, password)
    permissions: dict[str, dict[str, bool]] = client.get(
        "/api/v1/me/permissions", headers=mine
    ).json()["permissions"]
    return permissions


async def test_a_role_gives_only_its_own_crm_rights_not_the_base_role_bundle(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    leads = _create(client, boss, name="Только лиды", access={"crm.leads": "full"})
    chat = _create(client, boss, name="Только чат", access={"chats.internal": "full"})

    got = await _permissions_of(client, sessions, boss, int(leads["id"]), "leads@railtech.uz")  # type: ignore[call-overload]
    assert got["leads"]["take"] is True
    assert got["clients"] == {"read": False, "write": False}  # seed manager дал бы write
    assert got["deals"] == {"read": False, "write": False}
    assert got["users"] == {"read": False, "write": False}

    nothing = await _permissions_of(client, sessions, boss, int(chat["id"]), "chat@railtech.uz")  # type: ignore[call-overload]
    assert not any(v for actions in nothing.values() for v in actions.values())  # даже leads:read


async def test_the_system_admin_role_keeps_every_crm_right(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, boss = await setup_staff(client, sessions)
    (admin_role,) = legacy_ids(client, boss, ["ADMIN"])

    got = await _permissions_of(client, sessions, boss, admin_role, "admin2@railtech.uz")

    assert all(v for actions in got.values() for v in actions.values())


async def test_a_failed_policy_reload_is_not_a_500_and_is_retried_on_the_next_check(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, boss = await setup_staff(client, sessions)
    role = _create(client, boss, access={"crm.clients": "read"})
    account, password = await make_user(sessions, "who@railtech.uz", ["viewer"])
    client.patch(
        f"/api/v1/users/{account.id}", json={"platform_role_ids": [role["id"]]}, headers=boss
    )
    mine = login(client, account.email, password)
    assert client.get("/api/v1/users", headers=mine).status_code == 403

    calls = {"n": 0}
    real_reload = Rbac.reload

    async def flaky(self: Rbac) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("db is down")
        await real_reload(self)

    monkeypatch.setattr(Rbac, "reload", flaky)

    saved = patch_role(client, boss, role["id"], {"access": {"admin": "read"}})

    assert saved.status_code == 200, saved.text  # роль сохранена, ответ не 500
    assert calls["n"] == 1
    assert client.app.state.rbac.stale is True  # type: ignore[attr-defined]
    # Следующая проверка права перезагружает политики и видит новую роль.
    assert client.get("/api/v1/users", headers=mine).status_code == 200
    assert calls["n"] == 2
    assert client.app.state.rbac.stale is False  # type: ignore[attr-defined]
    assert employee


# --- матрицы ролей в /me для BFF Платформы (R-2) -----------------------------------------------


async def test_me_gives_the_employee_the_matrices_of_his_roles_and_users_does_not(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Рядовой сотрудник с созданной ролью читает в `/me` её матрицу (BFF считает по ней разделы);
    системная роль — матрица каталога; список `/users` матриц не несёт."""
    _, boss = await setup_staff(client, sessions)
    role = _create(
        client,
        boss,
        access={"crm.leads": "full", "eds.payments": "full"},
        restricted_fields=["totals_only"],
    )
    (director,) = legacy_ids(client, boss, ["DIRECTOR"])
    account, password = await make_user(sessions, "mixed@railtech.uz", ["viewer"])
    client.patch(
        f"/api/v1/users/{account.id}",
        json={"platform_role_ids": [role["id"], director]},
        headers=boss,
    )

    me = client.get("/api/v1/me", headers=login(client, account.email, password)).json()

    by_id = {r["id"]: r for r in me["platform_role_refs"]}
    assert by_id[role["id"]]["access"] == {"crm.leads": "full", "eds.payments": "full"}
    assert by_id[role["id"]]["restricted_fields"] == ["totals_only"]
    assert by_id[role["id"]]["system"] is False
    assert by_id[director]["access"] == dict(ROLE_ACCESS["DIRECTOR"])
    assert by_id[director]["restricted_fields"] == list(ROLE_RESTRICTED_FIELDS["DIRECTOR"])
    listed = client.get(f"/api/v1/users/{account.id}", headers=boss).json()
    assert all(set(r) == {"id", "name", "system", "code"} for r in listed["platform_role_refs"])
