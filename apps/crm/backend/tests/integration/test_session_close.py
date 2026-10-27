"""Смена пароля закрывает прочие сессии, текущая продолжается (W15-H8b; QUESTIONS п. 12 из #278)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import RefreshToken, User
from tests.integration.crm_helpers import PASSWORD, make_user

pytestmark = pytest.mark.integration
NEW_PASSWORD = "Another-secret-4242"


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def sign_in(client: TestClient, email: str) -> tuple[dict[str, str], str]:
    """Вход отдельным «устройством»: access и refresh-cookie (клиенты не делят cookie-jar)."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    refresh = response.cookies["rt_refresh"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, refresh


def refresh_with(client: TestClient, token: str) -> int:
    client.cookies.clear()
    client.cookies.set("rt_refresh", token, path="/api/v1/auth")
    status = client.post("/api/v1/auth/refresh").status_code
    client.cookies.clear()
    return status


async def test_changing_own_password_closes_other_sessions_and_keeps_this_one(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    phone, phone_refresh = sign_in(client, account.email)  # другое устройство
    laptop, laptop_refresh = sign_in(client, account.email)  # то, где меняют пароль

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=laptop,
    )
    assert changed.status_code == 200, changed.text
    new_refresh = changed.cookies["rt_refresh"]
    client.cookies.clear()
    current = {"Authorization": f"Bearer {changed.json()['access_token']}"}

    # Прочие сессии закрыты сразу: и access, и refresh; прежняя сессия этого устройства — тоже.
    for stale in (phone, laptop):
        assert client.get("/api/v1/me", headers=stale).status_code == 401
    assert refresh_with(client, phone_refresh) == 401
    assert refresh_with(client, laptop_refresh) == 401
    # Текущая продолжается и продлевается.
    assert client.get("/api/v1/me", headers=current).status_code == 200
    assert refresh_with(client, new_refresh) == 200
    # Вход со старым паролем невозможен, с новым — работает.
    old = client.post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD})
    assert old.status_code == 401
    fresh = client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 200


async def test_refresh_issued_before_the_change_is_refused_even_if_not_revoked(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Гонка refresh и сброса: токен, созданный до смены пароля, отвергается, семейство гасится."""
    account, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    _, refresh = sign_in(client, account.email)
    async with sessions() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id == account.id)
            .values(password_changed_at=datetime.now(UTC) + timedelta(seconds=30))
        )
    assert refresh_with(client, refresh) == 401
    async with sessions() as session:
        rows = list(
            await session.scalars(select(RefreshToken).where(RefreshToken.user_id == account.id))
        )
    assert rows
    assert all(row.revoked_at is not None for row in rows)


async def test_new_refresh_tokens_carry_the_application_clock(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """`created_at` refresh-токена ставит приложение, не БД: его сверяют с `password_changed_at`."""
    account, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    before = datetime.now(UTC)
    sign_in(client, account.email)
    after = datetime.now(UTC)
    async with sessions() as session:
        created = await session.scalar(
            select(RefreshToken.created_at).where(RefreshToken.user_id == account.id)
        )
    assert created is not None
    assert before <= created <= after


async def test_password_changed_at_is_the_application_clock_and_matches_the_new_session(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers, _ = sign_in(client, account.email)
    before = datetime.now(UTC)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    after = datetime.now(UTC)
    assert changed.status_code == 200
    async with sessions() as session:
        user = await session.get(User, account.id)
        live = list(
            await session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == account.id, RefreshToken.revoked_at.is_(None)
                )
            )
        )
    assert user is not None
    assert user.password_changed_at is not None
    assert before <= user.password_changed_at <= after
    # Единственный живой refresh — новой сессии, выпущен ровно на момент смены.
    assert [t.created_at for t in live] == [user.password_changed_at]
