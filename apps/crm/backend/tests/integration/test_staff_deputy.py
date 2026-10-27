"""Замещение на время отсутствия (W15-H6): назначение, период, очередь заместителя."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ForbiddenError, ValidationFailedError
from app.main import create_app
from app.models.auth import User
from app.models.leads import Lead
from app.security.audit import Actor
from app.services.staff_deputy import StaffDeputyService
from tests.integration.crm_helpers import escalated_lead, login, make_user

pytestmark = pytest.mark.integration
NOON = datetime(2026, 11, 5, 7, 0, tzinfo=UTC)  # 12:00 в Ташкенте
TODAY = date(2026, 11, 5)


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def svc(sessions: async_sessionmaker[AsyncSession], now: datetime = NOON) -> StaffDeputyService:
    return StaffDeputyService(sessions, lambda: now)


async def test_candidates_are_active_working_colleagues(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    me, _ = await make_user(sessions, "me@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "colleague@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "admin@railtech.uz", ["admin"])
    viewer, _ = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    gone, _ = await make_user(sessions, "gone@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == gone.id).values(is_active=False))

    found = {c.id for c in await svc(sessions).candidates(me.id)}
    assert found == {colleague.id, boss.id}
    assert viewer.id not in found
    assert me.id not in found


async def test_set_and_clear_deputy(sessions: async_sessionmaker[AsyncSession]) -> None:
    me, _ = await make_user(sessions, "me@railtech.uz", ["manager"])
    deputy, _ = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    service = svc(sessions)
    await service.set(Actor(me.id), me.id, deputy.id, TODAY, TODAY + timedelta(days=7))
    assert await service.deputy_name(deputy.id) == "deputy"
    assert [c.user_id for c in await service.covering(deputy.id)] == [me.id]

    await service.clear(Actor(me.id), me.id)
    assert await service.covering(deputy.id) == []
    await service.clear(Actor(me.id), me.id)  # повторная очистка — не ошибка


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("self", "deputy_is_self"),
        ("reversed", "deputy_period_reversed"),
        ("past", "deputy_period_past"),
        ("viewer", "deputy_not_colleague"),
        ("inactive", "deputy_not_colleague"),
        ("missing", "deputy_not_colleague"),
    ],
)
async def test_invalid_assignments(
    sessions: async_sessionmaker[AsyncSession], kind: str, reason: str
) -> None:
    me, _ = await make_user(sessions, "me@railtech.uz", ["manager"])
    viewer, _ = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    gone, _ = await make_user(sessions, "gone@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == gone.id).values(is_active=False))
    target = {
        "self": me.id, "reversed": gone.id, "past": gone.id,
        "viewer": viewer.id, "inactive": gone.id, "missing": 99999,
    }[kind]  # fmt: skip
    start, end = {
        "reversed": (TODAY + timedelta(days=5), TODAY),
        "past": (TODAY - timedelta(days=9), TODAY - timedelta(days=1)),
    }.get(kind, (TODAY, TODAY + timedelta(days=3)))
    with pytest.raises(ValidationFailedError) as caught:
        await svc(sessions).set(Actor(me.id), me.id, target, start, end)
    assert caught.value.details["reason"] == reason


async def test_covering_follows_the_period_in_the_absent_employee_calendar(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    me, _ = await make_user(sessions, "me@railtech.uz", ["manager"])
    deputy, _ = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    await svc(sessions).set(Actor(me.id), me.id, deputy.id, TODAY, TODAY + timedelta(days=2))

    def at(day: date, hour: int = 7) -> StaffDeputyService:
        return svc(sessions, datetime(day.year, day.month, day.day, hour, tzinfo=UTC))

    assert await at(TODAY - timedelta(days=1)).covering(deputy.id) == []
    assert len(await at(TODAY).covering(deputy.id)) == 1
    assert len(await at(TODAY + timedelta(days=2)).covering(deputy.id)) == 1
    assert await at(TODAY + timedelta(days=3)).covering(deputy.id) == []
    # 20:00 UTC в Ташкенте (UTC+5) уже следующие сутки: период закончился на час раньше по UTC.
    assert await at(TODAY + timedelta(days=2), 20).covering(deputy.id) == []
    # Отключённого замещаемого очередь не видна.
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == me.id).values(is_active=False))
    assert await at(TODAY).covering(deputy.id) == []


async def test_require_covering_refuses_strangers(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    me, _ = await make_user(sessions, "me@railtech.uz", ["manager"])
    deputy, _ = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    service = svc(sessions)
    await service.set(Actor(me.id), me.id, deputy.id, TODAY, TODAY)
    assert (await service.require_covering(deputy.id, me.id)).user_id == me.id
    with pytest.raises(ForbiddenError) as caught:
        await service.require_covering(other.id, me.id)
    assert caught.value.details["reason"] == "not_a_deputy"


async def test_inbox_on_behalf_of_only_for_the_deputy_in_period(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    absent, _ = await make_user(sessions, "absent@railtech.uz", ["manager"])
    deputy, deputy_password = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    stranger, stranger_password = await make_user(sessions, "stranger@railtech.uz", ["manager"])
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(owner_mode="human", assigned_user_id=absent.id)
        )
    today = datetime.now(UTC).date()
    await svc(sessions, datetime.now(UTC)).set(
        Actor(absent.id), absent.id, deputy.id, today - timedelta(days=1), today + timedelta(days=1)
    )

    own = login(client, deputy.email, deputy_password)
    covered = client.get(f"/api/v1/inbox?on_behalf_of={absent.id}", headers=own)
    assert covered.status_code == 200, covered.text
    assert [lead["id"] for lead in covered.json()["mine"]] == [lead_id]
    assert covered.json()["unassigned"] == []
    # Своя очередь заместителя от этого не меняется.
    assert client.get("/api/v1/inbox", headers=own).json()["mine"] == []
    covering = client.get("/api/v1/me/covering", headers=own).json()
    assert [(c["user_id"], c["full_name"]) for c in covering] == [(absent.id, "absent")]

    # Посторонний и сам замещаемый «за кого-то» очередь не получают.
    other = login(client, stranger.email, stranger_password)
    refused = client.get(f"/api/v1/inbox?on_behalf_of={absent.id}", headers=other)
    assert refused.status_code == 403
    assert refused.json()["details"]["reason"] == "not_a_deputy"
    assert client.get("/api/v1/me/covering", headers=other).json() == []


async def test_inbox_on_behalf_of_after_the_period_is_refused(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    absent, _ = await make_user(sessions, "absent@railtech.uz", ["manager"])
    deputy, password = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        today = datetime.now(UTC).date()
        await session.execute(
            update(User)
            .where(User.id == absent.id)
            .values(
                deputy_user_id=deputy.id,
                deputy_from=today - timedelta(days=10),
                deputy_to=today - timedelta(days=3),
            )
        )
    headers = login(client, deputy.email, password)
    response = client.get(f"/api/v1/inbox?on_behalf_of={absent.id}", headers=headers)
    assert response.status_code == 403


async def test_deputy_api_roundtrip(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    me, password = await make_user(sessions, "me@railtech.uz", ["manager"])
    deputy, _ = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    headers = login(client, me.email, password)
    candidates = client.get("/api/v1/me/deputy-candidates", headers=headers).json()
    assert [c["id"] for c in candidates] == [deputy.id]

    start = datetime.now(UTC).date() + timedelta(days=1)
    body = {
        "deputy_user_id": deputy.id,
        "date_from": start.isoformat(),
        "date_to": (start + timedelta(days=5)).isoformat(),
    }
    saved = client.put("/api/v1/me/deputy", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["deputy_user_id"] == deputy.id
    assert saved.json()["deputy_name"] == "deputy"
    assert client.get("/api/v1/me", headers=headers).json()["deputy_to"] == body["date_to"]
    bad = client.put("/api/v1/me/deputy", headers=headers, json={**body, "deputy_user_id": me.id})
    assert bad.status_code == 422
    assert bad.json()["details"]["reason"] == "deputy_is_self"
    cleared = client.delete("/api/v1/me/deputy", headers=headers).json()
    assert cleared["deputy_user_id"] is None
    assert cleared["deputy_name"] is None
