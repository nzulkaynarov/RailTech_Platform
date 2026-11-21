"""СЦ-9 P12: заместитель отвечает лиду замещаемого и забирает его; без замещения — отказ."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.leads import Lead, Message
from app.services.lead_messenger import LeadMessenger
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user

pytestmark = pytest.mark.integration
DAY = timedelta(days=1)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, sender: FakeSender
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        container = app.state.container
        container.__dict__["lead_messenger"] = LeadMessenger(sessions, sender)
        container.__dict__.pop("lead_service", None)
        yield test_client


async def deputize(
    sessions: async_sessionmaker[AsyncSession],
    owner_id: int,
    deputy_id: int,
    start: timedelta,
    end: timedelta,
) -> None:
    today = datetime.now(UTC).date()
    async with sessions() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id == owner_id)
            .values(deputy_user_id=deputy_id, deputy_from=today + start, deputy_to=today + end)
        )


class Setup:
    def __init__(self, lead_id: int, owner: Any, deputy: Any, other: Any, password: str) -> None:
        self.lead_id, self.owner, self.deputy, self.other = lead_id, owner, deputy, other
        self.password = password


@pytest.fixture
async def setup(client: TestClient, sessions: async_sessionmaker[AsyncSession]) -> Setup:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "owner@railtech.uz", ["manager"])
    deputy, _ = await make_user(sessions, "deputy@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    url = f"/api/v1/leads/{lead_id}/actions/take"
    assert client.post(url, headers=login(client, owner.email, password)).status_code == 200
    return Setup(lead_id, owner, deputy, other, password)


def post(
    client: TestClient, s: Setup, who: Any, path: str, body: dict[str, Any] | None = None
) -> Any:
    return client.post(
        f"/api/v1/leads/{s.lead_id}/{path}", json=body, headers=login(client, who.email, s.password)
    )


async def test_deputy_replies_and_it_is_journaled_on_behalf(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], setup: Setup, sender: FakeSender
) -> None:
    await deputize(sessions, setup.owner.id, setup.deputy.id, -DAY, DAY)
    answer = post(client, setup, setup.deputy, "messages", {"text": "Здравствуйте"})
    assert answer.status_code == 200
    async with sessions() as session:
        message = (await session.scalars(select(Message).where(Message.role == "manager"))).one()
        audits = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "lead.reply"))
        ).all()
    assert message.sent_by_user_id == setup.deputy.id
    assert message.meta["on_behalf_of_user_id"] == setup.owner.id
    assert [(a.actor_user_id, (a.after or {}).get("on_behalf_of_user_id")) for a in audits] == [
        (setup.deputy.id, setup.owner.id)
    ]
    # Лид остаётся у владельца: заместитель отвечает за него, а не забирает.
    async with sessions() as session:
        lead = await session.get(Lead, setup.lead_id)
    assert lead is not None
    assert lead.assigned_user_id == setup.owner.id
    assert sender.sent


async def test_owner_reply_has_no_behalf_mark(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], setup: Setup
) -> None:
    assert post(client, setup, setup.owner, "messages", {"text": "Добрый день"}).status_code == 200
    async with sessions() as session:
        message = (await session.scalars(select(Message).where(Message.role == "manager"))).one()
    assert "on_behalf_of_user_id" not in message.meta


async def test_deputy_takes_the_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], setup: Setup
) -> None:
    await deputize(sessions, setup.owner.id, setup.deputy.id, -DAY, DAY)
    assert post(client, setup, setup.deputy, "actions/take").status_code == 200
    async with sessions() as session:
        lead = await session.get(Lead, setup.lead_id)
        audit = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "lead.take", AuditLog.actor_user_id == setup.deputy.id
                )
            )
        ).one()
    assert lead is not None
    assert lead.assigned_user_id == setup.deputy.id
    assert (audit.after or {})["on_behalf_of_user_id"] == setup.owner.id


async def test_deputy_hands_the_lead_to_colleague(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], setup: Setup
) -> None:
    await deputize(sessions, setup.owner.id, setup.deputy.id, -DAY, DAY)
    handed = post(client, setup, setup.deputy, "actions/assign", {"user_id": setup.other.id})
    assert handed.status_code == 200
    async with sessions() as session:
        lead = await session.get(Lead, setup.lead_id)
    assert lead is not None
    assert lead.assigned_user_id == setup.other.id


@pytest.mark.parametrize(
    "case",
    [
        "no_deputyship",
        "period_over",
        "period_not_started",
        "other_user",
    ],
)
async def test_refused_without_active_deputyship(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], setup: Setup, case: str
) -> None:
    start, end = {
        "period_over": (-10 * DAY, -2 * DAY),
        "period_not_started": (3 * DAY, 9 * DAY),
    }.get(case, (-DAY, DAY))
    if case != "no_deputyship":
        await deputize(sessions, setup.owner.id, setup.deputy.id, start, end)
    who = setup.other if case == "other_user" else setup.deputy
    reply = post(client, setup, who, "messages", {"text": "x"})
    assert reply.status_code == 403
    assert reply.json()["details"]["reason"] == "not_lead_owner"
    assert post(client, setup, who, "actions/take").status_code == 409


async def test_acts_for_excludes_inactive_people(
    sessions: async_sessionmaker[AsyncSession], setup: Setup
) -> None:
    from app.services.staff_deputy import acts_for

    await deputize(sessions, setup.owner.id, setup.deputy.id, -DAY, DAY)
    async with sessions() as session:
        assert await acts_for(session, setup.deputy.id, setup.owner.id)
        assert not await acts_for(session, setup.owner.id, setup.owner.id)
        assert not await acts_for(session, setup.other.id, setup.owner.id)
    for who in (setup.deputy.id, setup.owner.id):
        async with sessions() as session, session.begin():
            await session.execute(update(User).where(User.id == who).values(is_active=False))
        async with sessions() as session:
            assert not await acts_for(session, setup.deputy.id, setup.owner.id)
        async with sessions() as session, session.begin():
            await session.execute(update(User).where(User.id == who).values(is_active=True))
