"""Передача лида коллеге, деактивация с переносом, повторная сделка клиента (ADR-0015)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.clients import Client
from app.models.leads import Lead
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user
from tests.integration.test_crm_actions import client, sender

pytestmark = pytest.mark.integration
__all__ = ["client", "sender"]


async def lead_row(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Lead:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        return lead


def act(
    client: TestClient, lead_id: int, action: str, headers: dict[str, str], **body: object
) -> Any:  # Response из httpx, который использует TestClient
    return client.post(f"/api/v1/leads/{lead_id}/actions/{action}", json=body, headers=headers)


async def test_hand_over_to_colleague_keeps_stage_and_tells_the_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "aziza@railtech.uz", ["manager"])
    viewer, _ = await make_user(sessions, "boss@railtech.uz", ["viewer"])
    me = login(client, owner.email, password)
    assert act(client, lead_id, "take", me).status_code == 200

    assert act(client, lead_id, "assign", me, user_id=viewer.id).status_code == 422
    assert act(client, lead_id, "assign", me, user_id=colleague.id).status_code == 200

    lead = await lead_row(sessions, lead_id)
    assert (lead.stage, lead.owner_mode, lead.assigned_user_id) == (
        "in_progress",
        "human",
        colleague.id,
    )
    assert "aziza" in sender.sent[-1][1]
    team = client.get("/api/v1/team", headers=me).json()
    assert {m["id"] for m in team} >= {owner.id, colleague.id}
    assert viewer.id not in {m["id"] for m in team}


async def test_return_to_bot_tells_the_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    me = login(client, owner.email, password)
    act(client, lead_id, "take", me)
    assert act(client, lead_id, "return_to_bot", me).status_code == 200
    assert "/human" in sender.sent[-1][1]


async def test_deactivation_requires_handing_over_active_leads(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    leaving, password = await make_user(sessions, "leaving@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "aziza@railtech.uz", ["manager"])
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    act(client, lead_id, "take", login(client, leaving.email, password))
    boss = login(client, admin.email, admin_password)

    refused = client.patch(f"/api/v1/users/{leaving.id}", json={"is_active": False}, headers=boss)
    assert refused.status_code == 409
    assert refused.json()["code"] == "user_has_active_leads"

    done = client.patch(
        f"/api/v1/users/{leaving.id}",
        json={"is_active": False, "transfer_to_user_id": colleague.id},
        headers=boss,
    )
    assert done.status_code == 200
    assert (await lead_row(sessions, lead_id)).assigned_user_id == colleague.id


async def test_customer_new_deal_goes_through_funnel_and_back_to_customer(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    me = login(client, owner.email, password)
    act(client, lead_id, "take", me)
    act(client, lead_id, "close_won", me)
    made = act(client, lead_id, "make_customer", me, new_client_name="Альфа")
    assert made.status_code == 201

    assert act(client, lead_id, "new_deal", me).status_code == 200
    lead = await lead_row(sessions, lead_id)
    assert (lead.stage, lead.owner_mode) == ("in_progress", "human")

    assert (
        act(client, lead_id, "close_lost", me, reason="бюджет на следующий год").status_code == 200
    )
    lead = await lead_row(sessions, lead_id)
    assert (lead.stage, lead.owner_mode) == ("customer", "bot")
    async with sessions() as session:
        assert (await session.scalars(select(Client))).one().id == lead.client_id


async def test_my_leads_show_unread_when_the_lead_writes_after_the_manager(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    me = login(client, owner.email, password)
    act(client, lead_id, "take", me)
    client.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "Добрый день!"}, headers=me)
    assert client.get("/api/v1/inbox", headers=me).json()["mine"][0]["unread"] is False

    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.last_lead_msg_at = datetime.now(UTC)
    assert client.get("/api/v1/inbox", headers=me).json()["mine"][0]["unread"] is True
