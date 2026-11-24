"""LH-1: ручки лида — закрыть с причиной, переназначить, «Спам/Тест/Дубль», правка контактов."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote, Message
from app.models.qualification import Escalation
from app.services.lead_messenger import LeadMessenger
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user

pytestmark = pytest.mark.integration


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


async def lead_row(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Lead:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    return lead


async def audited(sessions: async_sessionmaker[AsyncSession], action: str) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(select(AuditLog).where(AuditLog.action == action))
        return list(rows.all())


def url(lead_id: int, path: str) -> str:
    return f"/api/v1/leads/{lead_id}/{path}"


async def test_close_lost_with_reason_and_options(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "close@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    options = client.get("/api/v1/leads/close_options", headers=headers)
    assert options.status_code == 200
    assert options.json()["lost_reasons"]
    assert options.json()["won_by_erp"] is False
    reason = options.json()["lost_reasons"][0]
    assert client.post(url(lead_id, "actions/take"), headers=headers).status_code == 200
    lost = client.post(
        url(lead_id, "actions/close_lost"),
        json={"lost_reason": reason, "reason": "дорого"},
        headers=headers,
    )
    assert lost.status_code == 200
    assert (await lead_row(sessions, lead_id)).stage == "lost"
    async with sessions() as session:
        deal = (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).one()
    assert (deal.stage, deal.lost_reason) == ("lost", reason)
    assert len(await audited(sessions, "lead.close_lost")) == 1


async def test_assign_taken_lead_to_colleague(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "owner@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "colleague@railtech.uz", ["manager"])
    stranger, _ = await make_user(sessions, "stranger@railtech.uz", ["manager"])
    me = login(client, owner.email, password)
    assert client.post(url(lead_id, "actions/take"), headers=me).status_code == 200
    foreign = client.post(
        url(lead_id, "actions/assign"),
        json={"user_id": colleague.id},
        headers=login(client, stranger.email, password),
    )
    assert foreign.status_code == 403
    done = client.post(url(lead_id, "actions/assign"), json={"user_id": colleague.id}, headers=me)
    assert done.status_code == 200
    assert (await lead_row(sessions, lead_id)).assigned_user_id == colleague.id
    assert len(await audited(sessions, "lead.assign")) == 1


@pytest.mark.parametrize("kind", ["spam", "test"])
async def test_discard_hides_lead_and_closes_escalation(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], kind: str
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, f"{kind}@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert client.get("/api/v1/leads", headers=headers).json()["total"] == 1
    done = client.post(url(lead_id, "actions/discard"), json={"kind": kind}, headers=headers)
    assert done.status_code == 200, done.text
    lead = await lead_row(sessions, lead_id)
    assert (lead.stage, lead.discarded_kind, lead.owner_mode) == ("lost", kind, "bot")
    async with sessions() as session:
        escalation = (await session.scalars(select(Escalation))).one()
    assert (escalation.status, escalation.outcome) == ("closed", f"discarded_{kind}")
    assert client.get("/api/v1/leads", headers=headers).json()["total"] == 0
    inbox = client.get("/api/v1/inbox", headers=headers).json()
    assert inbox["escalations"] == inbox["mine"] == inbox["unassigned"] == []
    assert len(await audited(sessions, f"lead.discard_{kind}")) == 1
    again = client.post(url(lead_id, "actions/discard"), json={"kind": kind}, headers=headers)
    assert again.status_code in (404, 409, 422)


async def test_discard_test_anonymises_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "erase@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert client.post(url(lead_id, "actions/discard"), json={"kind": "test"}, headers=headers)
    lead = await lead_row(sessions, lead_id)
    assert lead.erased_at is not None
    assert lead.display_name == ""
    async with sessions() as session:
        texts = (await session.scalars(select(Message.text))).all()
        notes = (await session.scalars(select(LeadNote.text))).all()
    assert "Сколько стоит?" not in texts
    assert "Сколько стоит?" not in notes
    # an erased lead is gone for the API, like after /delete in the bot
    assert client.get(f"/api/v1/leads/{lead_id}", headers=headers).status_code == 404


async def test_spam_keeps_messages_but_test_erases_only_test(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "spamkeeps@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert client.post(url(lead_id, "actions/discard"), json={"kind": "spam"}, headers=headers)
    lead = await lead_row(sessions, lead_id)
    assert lead.erased_at is None
    assert lead.display_name == "Азиз"


async def test_discard_duplicate_links_to_target(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first = await escalated_lead(sessions, 5001)
    second = await escalated_lead(sessions, 5002)
    manager, password = await make_user(sessions, "dup@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    bare = client.post(url(second, "actions/discard"), json={"kind": "duplicate"}, headers=headers)
    assert bare.status_code == 422
    assert bare.json()["details"]["field"] == "duplicate_of"
    itself = client.post(
        url(second, "actions/discard"),
        json={"kind": "duplicate", "duplicate_of": second},
        headers=headers,
    )
    assert itself.status_code == 422
    done = client.post(
        url(second, "actions/discard"),
        json={"kind": "duplicate", "duplicate_of": first},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    lead = await lead_row(sessions, second)
    assert (lead.discarded_kind, lead.duplicate_of_lead_id) == ("duplicate", first)
    card = client.get(f"/api/v1/leads/{second}", headers=headers).json()
    assert (card["discarded_kind"], card["duplicate_of_lead_id"]) == ("duplicate", first)
    # the lead it points to cannot itself be a discarded one
    third = await escalated_lead(sessions, 5003)
    chained = client.post(
        url(third, "actions/discard"),
        json={"kind": "duplicate", "duplicate_of": second},
        headers=headers,
    )
    assert chained.status_code == 422


async def test_discard_not_for_a_client_and_not_for_a_foreign_lead(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "own2@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "oth2@railtech.uz", ["manager"])
    assert (
        client.post(
            url(lead_id, "actions/take"), headers=login(client, owner.email, password)
        ).status_code
        == 200
    )
    foreign = client.post(
        url(lead_id, "actions/discard"),
        json={"kind": "spam"},
        headers=login(client, other.email, password),
    )
    assert foreign.status_code == 403
    assert (await lead_row(sessions, lead_id)).discarded_kind is None


async def test_reopen_discarded_lead_by_take(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "reopen@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert client.post(url(lead_id, "actions/discard"), json={"kind": "spam"}, headers=headers)
    assert client.post(url(lead_id, "actions/take"), headers=headers).status_code == 200
    lead = await lead_row(sessions, lead_id)
    assert (lead.stage, lead.discarded_kind) == ("in_progress", None)
    assert client.get("/api/v1/leads", headers=headers).json()["total"] == 1


def patch(client: TestClient, lead_id: int, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/leads/{lead_id}", json=body, headers=headers)


async def test_update_contacts_normalises_and_audits(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "edit@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    done = patch(
        client,
        lead_id,
        headers,
        {
            "name": "  Азиз Каримов ",
            "phone": "90 123-45-67",
            "email": " Aziz@Example.COM ",
            "company": "ООО Ромашка",
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["duplicates"] == []
    lead = await lead_row(sessions, lead_id)
    assert (lead.display_name, lead.phone_e164, lead.email, lead.company_name) == (
        "Азиз Каримов",
        "+998901234567",
        "aziz@example.com",
        "ООО Ромашка",
    )
    journal = await audited(sessions, "lead.update_contacts")
    assert len(journal) == 1
    assert journal[0].after is not None
    assert journal[0].after["fields"] == ["company", "email", "name", "phone"]
    cleared = patch(client, lead_id, headers, {"company": ""})
    assert cleared.status_code == 200
    assert (await lead_row(sessions, lead_id)).company_name is None


async def test_update_contacts_rejects_bad_values(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    manager, password = await make_user(sessions, "bad@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    phone = patch(client, lead_id, headers, {"phone": "12-34"})
    assert phone.status_code == 422
    assert (phone.json()["details"]["field"], phone.json()["details"]["reason"]) == (
        "phone",
        "invalid_phone",
    )
    email = patch(client, lead_id, headers, {"email": "not-an-email"})
    assert (email.status_code, email.json()["details"]["field"]) == (422, "email")
    name = patch(client, lead_id, headers, {"name": "  "})
    assert (name.status_code, name.json()["details"]["field"]) == (422, "name")
    lead = await lead_row(sessions, lead_id)
    assert (lead.display_name, lead.phone_e164, lead.email) == ("Азиз", None, None)


async def test_update_contacts_warns_about_duplicates(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first = await escalated_lead(sessions, 5001)
    second = await escalated_lead(sessions, 5002)
    manager, password = await make_user(sessions, "warn@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert (
        patch(
            client, first, headers, {"phone": "+998901234567", "email": "a@example.com"}
        ).status_code
        == 200
    )
    answer = patch(
        client, second, headers, {"phone": "+998 90 123 45 67", "email": "A@example.com"}
    )
    assert answer.status_code == 200
    found = answer.json()["duplicates"]
    assert {(d["kind"], d["id"], d["field"]) for d in found} == {
        ("lead", first, "phone"),
        ("lead", first, "email"),
    }
    # warning only: the edit is saved
    assert (await lead_row(sessions, second)).phone_e164 == "+998901234567"


async def test_update_contacts_of_a_foreign_lead_is_forbidden(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    owner, password = await make_user(sessions, "own3@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "oth3@railtech.uz", ["manager"])
    assert (
        client.post(
            url(lead_id, "actions/take"), headers=login(client, owner.email, password)
        ).status_code
        == 200
    )
    answer = patch(client, lead_id, login(client, other.email, password), {"company": "Чужая"})
    assert answer.status_code == 403
    assert (await lead_row(sessions, lead_id)).company_name is None
