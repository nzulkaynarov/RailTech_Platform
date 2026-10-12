"""Контакты клиента (Q-011): CRUD, один основной, подсказки из Telegram (Q-020), матрица ролей."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.leads import TelegramIdentity
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def _client_with_identity(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with sessions() as session, session.begin():
        row = Client(name="ООО Рельс")
        session.add(row)
        await session.flush()
        identity = TelegramIdentity(
            tg_user_id=7101,
            tg_first_name="Алишер",
            phone_e164="+998901234567",
            client_id=row.id,
            verified_at=datetime.now(UTC),
        )
        session.add(identity)
        await session.flush()
        return row.id, identity.id


async def test_contacts_crud_primary_and_telegram_suggestion(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, identity_id = await _client_with_identity(sessions)
    manager, password = await make_user(sessions, "contacts@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)
    url = f"/api/v1/clients/{client_id}/contacts"

    listed = client.get(url, headers=auth).json()
    assert listed["contacts"] == []
    assert listed["suggestions"][0]["telegram_identity_id"] == identity_id
    assert listed["suggestions"][0]["full_name"] == "Алишер"

    bad = client.post(url, headers=auth, json={"full_name": "A", "phone": "abc"})
    assert bad.status_code == 422
    assert bad.json()["details"] == {"reason": "invalid_phone", "field": "phone"}

    first = client.post(
        url,
        headers=auth,
        json={
            "full_name": "Алишер",
            "phone": "+998901234567",
            "is_primary": True,
            "telegram_identity_id": identity_id,
        },
    )
    assert first.status_code == 201, first.text
    second = client.post(
        url,
        headers=auth,
        json={
            "full_name": "Бобур",
            "phone": "998 90 765 43 21",
            "email": " B@Rail.UZ ",
            "is_primary": True,
        },
    )
    assert second.status_code == 201, second.text

    listed = client.get(url, headers=auth).json()
    assert listed["suggestions"] == []
    primary = [c for c in listed["contacts"] if c["is_primary"]]
    assert [c["full_name"] for c in primary] == ["Бобур"]
    assert primary[0]["phone_e164"] == "+998907654321"
    assert primary[0]["email"] == "b@rail.uz"

    contact_id = second.json()["id"]
    updated = client.put(
        f"{url}/{contact_id}", headers=auth, json={"full_name": "Бобур Т.", "position": "CEO"}
    )
    assert updated.status_code == 200
    assert client.delete(f"{url}/{contact_id}", headers=auth).status_code == 200
    assert client.delete(f"{url}/{contact_id}", headers=auth).status_code == 404

    async with sessions() as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
        left = (await session.scalars(select(ClientContact))).all()
    assert {"client.contact_create", "client.contact_update", "client.contact_delete"} <= set(
        actions
    )
    assert [c.full_name for c in left] == ["Алишер"]


async def test_viewer_reads_but_cannot_write(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await _client_with_identity(sessions)
    viewer, password = await make_user(sessions, "viewer-contacts@railtech.uz", ["viewer"])
    auth = login(client, viewer.email, password)
    url = f"/api/v1/clients/{client_id}/contacts"
    assert client.get(url, headers=auth).status_code == 200
    assert client.post(url, headers=auth, json={"full_name": "X"}).status_code == 403


async def test_foreign_telegram_identity_is_rejected(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, identity_id = await _client_with_identity(sessions)
    async with sessions() as session, session.begin():
        other = Client(name="Другой")
        session.add(other)
        await session.flush()
        other_id = other.id
    manager, password = await make_user(sessions, "contacts2@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)
    response = client.post(
        f"/api/v1/clients/{other_id}/contacts",
        headers=auth,
        json={"full_name": "X", "telegram_identity_id": identity_id},
    )
    assert response.status_code == 422
    assert response.json()["details"]["field"] == "telegram_identity_id"
    assert client_id != other_id
