"""Мастер первого запуска на реальном Postgres: код, первый админ, 409 навсегда, гонка, аудит."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError
from app.main import create_app
from app.models.auth import AuditLog
from app.security.audit import Actor
from app.services.users import UserService

pytestmark = pytest.mark.integration

BODY = {"email": "owner@railtech.uz", "full_name": "Владелец", "password": "Sup3rSecretPass"}


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def _code(client: TestClient) -> str:
    gate = client.app.state.container.setup_service._gate  # type: ignore[attr-defined]
    assert gate.code
    return str(gate.code)


async def test_first_run_creates_admin_once(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    assert client.get("/api/v1/setup/state").json() == {"needs_setup": True}
    wrong = client.post("/api/v1/setup/admin", json={**BODY, "code": "WRONGCODE1234567"})
    assert wrong.status_code == 422
    assert wrong.json()["details"]["reason"] == "setup_code_invalid"

    ok = client.post("/api/v1/setup/admin", json={**BODY, "code": _code(client).lower()})
    assert ok.status_code == 200, ok.text
    assert ok.json()["must_change_password"] is False
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get("/api/v1/setup/checklist", headers=headers).status_code == 200

    assert client.get("/api/v1/setup/state").json() == {"needs_setup": False}
    again = client.post("/api/v1/setup/admin", json={**BODY, "code": "ANYTHING12345678"})
    assert again.status_code == 409
    assert again.json()["details"]["reason"] == "setup_done"
    async with sessions() as session:
        count = await session.scalar(
            select(func.count()).where(AuditLog.action == "setup.admin_created")
        )
    assert count == 1


async def test_checklist_has_platform_steps(client: TestClient) -> None:
    """W13C-F1 (Q-W13-A4-2): шаги `erp`, `mail`, `first_employee` приходят из CRM, не из BFF."""
    ok = client.post("/api/v1/setup/admin", json={**BODY, "code": _code(client)})
    assert ok.status_code == 200, ok.text
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}

    first = client.get("/api/v1/setup/checklist", headers=headers).json()
    done = {i["key"]: i["done"] for i in first["items"]}
    assert {"erp", "mail", "first_employee"} <= set(done)
    assert first["total"] == len(first["items"])
    assert done["first_employee"] is False  # кроме администратора сотрудников нет
    links = {i["key"]: i["link"] for i in first["items"]}
    assert links["erp"] == "/integrations"
    assert links["first_employee"] == "/users"

    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "colleague@railtech.uz", "full_name": "Коллега", "roles": ["viewer"]},
    )
    assert created.status_code == 201, created.text
    second = client.get("/api/v1/setup/checklist", headers=headers).json()
    assert {i["key"]: i["done"] for i in second["items"]}["first_employee"] is True
    assert second["done"] == first["done"] + 1


async def test_checklist_survives_hanging_erp_and_broken_connector(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Зависшая ERP не задерживает чек-лист (пробы нет); сбой чтения коннектора — шаг «не готов»."""
    ok = client.post("/api/v1/setup/admin", json={**BODY, "code": _code(client)})
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    container = client.app.state.container  # type: ignore[attr-defined]

    async def hang() -> None:
        await asyncio.sleep(3600)

    async def broken() -> None:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(container.erp_connector, "health_facts", hang)
    monkeypatch.setattr(container.smtp_connector, "resolution", broken)
    monkeypatch.setattr(container.erp_connector, "resolution", broken)

    response = client.get("/api/v1/setup/checklist", headers=headers)

    assert response.status_code == 200, response.text
    done = {i["key"]: i["done"] for i in response.json()["items"]}
    assert done["erp"] is False
    assert done["mail"] is False


async def test_parallel_first_admins_only_one_wins(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = UserService(sessions)
    results = await asyncio.gather(
        service.create_first_admin(
            "first@railtech.uz", "Первый", "Sup3rSecretPass", Actor.system()
        ),
        service.create_first_admin(
            "second@railtech.uz", "Второй", "Sup3rSecretPass", Actor.system()
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(r, int) for r in results) == 1
    assert sum(isinstance(r, ConflictError) for r in results) == 1
