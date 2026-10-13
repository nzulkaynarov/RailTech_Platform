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
