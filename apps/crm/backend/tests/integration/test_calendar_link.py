"""Секретная ссылка календаря: выдача хранит только sha256, повтор заменяет, отключение отзывает."""

from collections.abc import Iterator
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.repositories import users as repo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def stored_hash(sessions: async_sessionmaker[AsyncSession], user_id: int) -> str | None:
    async with sessions() as session:
        user = await repo.get(session, user_id)
        assert user is not None
        return user.calendar_token_hash


async def test_issue_keeps_only_the_hash_and_rotation_replaces_it(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "cal1@railtech.uz", ["manager"])
    headers = login(client, account.email, PASSWORD)

    first = client.post("/api/v1/me/calendar-link", headers=headers)
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    assert len(token) >= 43  # 32 bytes in base64url
    stored = await stored_hash(sessions, account.id)
    assert stored == sha256(token.encode()).hexdigest()
    assert stored != token

    second = client.post("/api/v1/me/calendar-link", headers=headers)
    assert second.json()["token"] != token
    assert (
        await stored_hash(sessions, account.id)
        == sha256(second.json()["token"].encode()).hexdigest()
    )


async def test_deactivation_drops_the_link(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "cal2@railtech.uz", ["manager"])
    headers = login(client, account.email, PASSWORD)
    assert client.post("/api/v1/me/calendar-link", headers=headers).status_code == 200
    assert await stored_hash(sessions, account.id) is not None

    await UserService(sessions).update(Actor.system(), account.id, UserPatch(is_active=False))
    assert await stored_hash(sessions, account.id) is None
