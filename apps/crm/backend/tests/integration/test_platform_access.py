"""Доступ к ERP управляется из CRM (FIX-11, M3-CRM-06): `platform_access`, очередь, аудит, SSO.

Сквозной путь на настоящем Postgres: админ меняет `platform_access` → в очередь уходит
`provision`/`revoke` (запись вместо Procrastinate), аудит `platform_access.granted|revoked`, `/me` и
`/users` отдают список, SSO-токен без доступа — 403. Ошибки ERP пользователю не показываются.
"""

from collections.abc import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog, User
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration
SSO_SECRET = "integration-sso-secret-for-tests-only"


class Queue:
    """Вместо Procrastinate: что поставили в очередь синхронизации с ERP."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, int]] = []
        self.broken = False

    async def __call__(self, action: str, user_id: int) -> None:
        if self.broken:
            raise ConnectionError("queue is down")
        self.jobs.append((action, user_id))


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
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        container.__dict__["user_service"] = UserService(sessions, erp_sync=queue)
        container.__dict__.pop("sso_service", None)
        yield test_client


async def audit_actions(sessions: async_sessionmaker[AsyncSession], prefix: str) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditLog).where(AuditLog.action.like(f"{prefix}%")).order_by(AuditLog.id)
        )
        return list(rows)


async def test_default_is_crm_only_and_visible_in_me_and_users(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    boss = login(client, admin.email, password)

    assert client.get("/api/v1/me", headers=boss).json()["platform_access"] == ["crm"]
    listed = client.get("/api/v1/users", headers=boss).json()
    assert [u["platform_access"] for u in listed] == [["crm"]]


async def test_grant_queues_provisioning_and_audits(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)

    response = client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )

    assert response.status_code == 200
    assert response.json()["platform_access"] == ["crm", "erp"]
    assert queue.jobs == [("provision", manager.id)]
    (entry,) = await audit_actions(sessions, "platform_access")
    assert entry.action == "platform_access.granted"
    assert entry.entity_id == str(manager.id)
    assert entry.actor_user_id == admin.id
    assert entry.before == {"platform_access": ["crm"]}
    assert entry.after == {"platform_access": ["crm", "erp"]}


async def test_revoke_queues_session_revocation_and_audits(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )
    queue.jobs.clear()

    response = client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm"]}, headers=boss
    )

    assert response.status_code == 200
    assert queue.jobs == [("revoke", manager.id)]
    actions = [e.action for e in await audit_actions(sessions, "platform_access")]
    assert actions == ["platform_access.granted", "platform_access.revoked"]


async def test_unrelated_update_does_not_touch_erp(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)

    client.patch(f"/api/v1/users/{manager.id}", json={"tg_user_id": 777}, headers=boss)
    client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm"]}, headers=boss
    )  # без изменений

    assert queue.jobs == []
    assert await audit_actions(sessions, "platform_access") == []


async def test_role_change_and_deactivation_of_a_user_with_erp_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )
    queue.jobs.clear()

    client.patch(f"/api/v1/users/{manager.id}", json={"roles": ["viewer"]}, headers=boss)
    assert queue.jobs == [("provision", manager.id)]  # права ERP следуют за ролью CRM

    queue.jobs.clear()
    client.patch(f"/api/v1/users/{manager.id}", json={"is_active": False}, headers=boss)
    assert queue.jobs == [("revoke", manager.id)]  # ушёл из команды — ERP закрыта


@pytest.mark.parametrize(
    "body",
    [
        {"platform_access": ["erp"]},  # CRM есть у всех
        {"platform_access": []},
        {"platform_access": ["crm", "billing"]},
        {"platform_access": "erp"},
    ],
)
async def test_invalid_platform_access_is_rejected(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    queue: Queue,
    body: dict[str, object],
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)

    response = client.patch(f"/api/v1/users/{manager.id}", json=body, headers=boss)

    assert response.status_code == 422
    assert queue.jobs == []


async def test_only_admin_changes_platform_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    me = login(client, manager.email, password)

    response = client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=me
    )

    assert response.status_code == 403
    assert queue.jobs == []
    assert client.get("/api/v1/me", headers=me).json()["platform_access"] == ["crm"]


async def test_broken_queue_does_not_fail_the_request_and_shows_in_the_feed(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], queue: Queue
) -> None:
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    queue.broken = True

    response = client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )

    assert response.status_code == 200  # ошибка очереди не уходит пользователю
    async with sessions() as session:
        row = await session.get(User, manager.id)
        assert row is not None
        assert row.platform_access == ["crm", "erp"]
        assert row.erp_sync_error is not None


async def test_sso_token_matrix_without_access_there_is_no_switch(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Матрица M3-CRM-06: без доступа в ERP — ни кнопки (`/me`), ни токена (403)."""
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss = login(client, admin.email, admin_password)
    me = login(client, manager.email, password)

    denied = client.post("/api/v1/auth/sso/token", headers=me)
    assert denied.status_code == 403
    assert denied.json()["details"]["reason"] == "platform_access_denied"
    assert "erp" not in client.get("/api/v1/me", headers=me).json()["platform_access"]

    client.patch(
        f"/api/v1/users/{manager.id}", json={"platform_access": ["crm", "erp"]}, headers=boss
    )
    allowed = client.post("/api/v1/auth/sso/token", headers=me)
    assert allowed.status_code == 200
    claims = jwt.decode(
        allowed.json()["token"], SSO_SECRET, algorithms=["HS256"], audience="erp", issuer="crm"
    )
    assert claims["sub"] == str(manager.id)
    assert "quote.view_cost_margin" not in claims["permissions"]
    assert "erp" in client.get("/api/v1/me", headers=me).json()["platform_access"]

    client.patch(f"/api/v1/users/{manager.id}", json={"platform_access": ["crm"]}, headers=boss)
    assert client.post("/api/v1/auth/sso/token", headers=me).status_code == 403


@pytest.mark.parametrize("value", [["erp"], [], ["crm", "billing"], {"crm": True}, "crm"])
async def test_database_refuses_inconsistent_platform_access(
    sessions: async_sessionmaker[AsyncSession], value: object
) -> None:
    """Страховка схемы: CRM есть у каждого, других систем кроме ERP нет, значение — массив."""
    from sqlalchemy.exc import IntegrityError

    row = User(email="x@railtech.uz", full_name="X", password_hash="x", platform_access=value)
    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            session.add(row)


async def test_column_default_is_crm_only(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        row = User(email="y@railtech.uz", full_name="Y", password_hash="y")
        session.add(row)
        await session.flush()
        await session.refresh(row)
        assert row.platform_access == ["crm"]
        assert row.erp_sync_error is None
