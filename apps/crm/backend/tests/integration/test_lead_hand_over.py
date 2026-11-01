"""«Передать менеджеру» первой линией (D17G-1, DECISIONS 2026-11-01 п. 1) — на Postgres.

Делопроизводитель (шаблон `tpl:REGISTRAR`: `crm.leads` — чтение, `crm.leads.triage` — полный)
разбирает лида и передаёт его менеджеру-универсалу с запиской: лид у ответственного, передача бота
дополнена причиной `handed_over` и запиской (или открыта новая), клиенту ничего не уходит,
менеджеру — колокольчик. «Забрать», ответ клиенту и «Вернуть боту» делопроизводителю закрыты;
забрать переданного лида может только ответственный.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.leads import Lead, LeadNote
from app.models.qualification import Escalation
from app.models.staff_tickets import StaffNotification
from app.repositories import leads as repo
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.lead_messenger import LeadMessenger
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import FakeSender, escalated_lead, login, make_user

pytestmark = pytest.mark.integration

NOTE = "Нужен расчёт 40 шпал к 15.11, звонить после обеда"


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


async def _staff(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], email: str, code: str
) -> tuple[int, dict[str, str]]:
    account, password = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        (role,) = await prepo.by_codes(session, [code])
    await UserService(sessions).update(
        Actor.system(), account.id, UserPatch(platform_role_ids=[role.id])
    )
    return account.id, login(client, account.email, password)


async def _bot_lead(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Лид в диалоге с ботом, без передачи."""
    async with sessions() as session, session.begin():
        lead, _, conversation = await repo.create_lead_with_identity(
            session,
            tg_user_id=6101,
            username="bobur",
            first_name="Бобур",
            chat_id=6101,
            language="ru",
            identity=None,
        )
        lead.display_name, lead.stage, lead.owner_mode = "Бобур", "engaged", "bot"
        await repo.add_message(
            session, conversation_id=conversation.id, role="lead", text="Нужны шпалы"
        )
        return lead.id


async def test_registrar_hands_the_lead_over_and_the_manager_takes_it(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await escalated_lead(sessions)
    clerk_id, clerk = await _staff(client, sessions, "clerk@railtech.uz", "tpl:REGISTRAR")
    seller_id, seller = await _staff(client, sessions, "seller@railtech.uz", "tpl:MANAGER_ALL")
    _, other = await _staff(client, sessions, "other@railtech.uz", "tpl:MANAGER_ALL")

    # Первая линия не забирает, не отвечает клиенту и не возвращает боту.
    base = f"/api/v1/leads/{lead_id}"
    assert client.post(f"{base}/actions/take", headers=clerk).status_code == 403
    reply = client.post(f"{base}/messages", json={"text": "Здравствуйте"}, headers=clerk)
    assert reply.status_code == 403
    assert client.post(f"{base}/actions/return_to_bot", json={}, headers=clerk).status_code == 403

    targets = client.get("/api/v1/leads/handover_targets", headers=clerk)
    assert targets.status_code == 200, targets.text
    ids = {row["id"] for row in targets.json()}
    assert seller_id in ids
    assert clerk_id not in ids
    assert client.get("/api/v1/leads/handover_targets", headers=seller).status_code == 403

    # Передать можно только тому, кто ведёт лидов.
    wrong = client.post(
        f"{base}/actions/hand_over", json={"user_id": clerk_id, "note": NOTE}, headers=clerk
    )
    assert wrong.status_code == 422
    assert wrong.json()["details"]["reason"] == "inactive_colleague"
    empty = client.post(
        f"{base}/actions/hand_over", json={"user_id": seller_id, "note": ""}, headers=clerk
    )
    assert empty.status_code == 422

    done = client.post(
        f"{base}/actions/hand_over",
        json={"user_id": seller_id, "note": NOTE, "request_type": "goods"},
        headers=clerk,
    )
    assert done.status_code == 200, done.text
    assert sender.sent == []  # клиенту ничего не уходит

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        escalation = (await session.scalars(select(Escalation))).one()
        notes = (await session.scalars(select(LeadNote))).all()
        bell = (
            await session.scalars(
                select(StaffNotification).where(StaffNotification.user_id == seller_id)
            )
        ).all()
    assert lead is not None
    assert (lead.assigned_user_id, lead.owner_mode, lead.stage) == (seller_id, "paused", "handoff")
    assert escalation.status == "open"
    assert escalation.reason_codes == ["price_or_contract_asked", "handed_over"]
    assert escalation.priority == "hot"
    assert (escalation.reason_text, escalation.handed_by_user_id, escalation.request_type) == (
        NOTE,
        clerk_id,
        "goods",
    )
    assert escalation.sla_due_at is not None
    assert [(n.user_id, n.text, n.visible_to_bot) for n in notes] == [(clerk_id, NOTE, False)]
    assert [(b.kind, b.object_kind, b.object_number) for b in bell] == [
        ("lead_handed_over", "lead", f"L-{lead_id:04d}")
    ]

    inbox = client.get("/api/v1/inbox", headers=seller).json()
    (row,) = [r for r in inbox["escalations"] if r["id"] == lead_id]
    assert row["assigned_user_id"] == seller_id
    assert row["escalation"]["handed_by_user_id"] == clerk_id
    assert row["escalation"]["handed_by_user_name"] == "clerk"  # имя первой линии без `/users`
    assert row["escalation"]["request_type"] == "goods"

    # Забирает только ответственный; другой менеджер — 409 с именем.
    taken = client.post(f"{base}/actions/take", headers=other)
    assert taken.status_code == 409
    assert taken.json()["details"]["reason"] == "lead_taken"
    assert client.post(f"{base}/actions/take", headers=seller).status_code == 200
    assert len(sender.sent) == 1  # «к вам подключился менеджер» — после «Забрать»

    # Лида ведёт менеджер — первая линия его не перехватывает.
    again = client.post(
        f"{base}/actions/hand_over", json={"user_id": seller_id, "note": NOTE}, headers=clerk
    )
    assert again.status_code == 409
    assert again.json()["details"]["reason"] == "lead_taken"


async def test_a_lead_without_a_handoff_gets_a_new_one(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], sender: FakeSender
) -> None:
    lead_id = await _bot_lead(sessions)
    clerk_id, clerk = await _staff(client, sessions, "clerk2@railtech.uz", "tpl:REGISTRAR")
    seller_id, _ = await _staff(client, sessions, "seller2@railtech.uz", "tpl:MANAGER_ALL")
    done = client.post(
        f"/api/v1/leads/{lead_id}/actions/hand_over",
        json={"user_id": seller_id, "note": NOTE},
        headers=clerk,
    )
    assert done.status_code == 200, done.text
    assert sender.sent == []
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        escalation = (await session.scalars(select(Escalation))).one()
    assert lead is not None
    assert (lead.assigned_user_id, lead.owner_mode, lead.stage) == (seller_id, "paused", "handoff")
    assert (escalation.status, escalation.priority, escalation.reason_codes) == (
        "open",
        "warm",
        ["handed_over"],
    )
    assert (escalation.handed_by_user_id, escalation.request_type) == (clerk_id, None)
