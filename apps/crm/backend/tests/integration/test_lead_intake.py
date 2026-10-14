"""Источники лидов (M3-CRM-05): форма с сайта, «Новый лид» вручную, склейка с Telegram по номеру."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.web_form import issue_form_token
from app.main import create_app
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.leads import Conversation, Lead, LeadNote, TelegramIdentity
from app.models.qualification import Escalation, StageTransition
from app.services.client_bot import ClientBotService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import escalated_lead, login, make_user

pytestmark = pytest.mark.integration

PHONE = "+998901234567"


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def form_token(settings: Settings, age_s: int = 10) -> str:
    key = settings.jwt_secret.get_secret_value().encode()
    return issue_form_token(key, datetime.now(UTC) - timedelta(seconds=age_s))


def web_body(settings: Settings, **patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Алишер",
        "company": "ООО Рельс",
        "phone": "90 123 45 67",
        "email": "A@Rail.UZ",
        "text": "Нужна интеграция POS с 1С",
        "language": "uz",
        "form_token": form_token(settings),
        "consent": True,
    }
    body.update(patch)
    return body


async def audit_actions(sessions: async_sessionmaker[AsyncSession]) -> set[str]:
    async with sessions() as session:
        return set((await session.scalars(select(AuditLog.action))).all())


async def test_web_form_creates_lead_in_inbox_without_auth(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    token = client.get("/api/v1/leads/web/token")
    assert token.status_code == 200
    assert token.json()["min_fill_seconds"] == 3

    accepted = client.post("/api/v1/leads/web", json=web_body(live_settings))
    assert accepted.status_code == 202, accepted.text
    lead_id = accepted.json()["lead_id"]
    assert isinstance(lead_id, int)

    manager, password = await make_user(sessions, "web-mgr@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)
    inbox = client.get("/api/v1/inbox", headers=auth).json()
    assert [lead["id"] for lead in inbox["unassigned"]] == [lead_id]
    assert inbox["unassigned"][0]["source"] == "web"

    detail = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()
    assert detail["source"] == "web"
    assert detail["company_name"] == "ООО Рельс"
    assert detail["email"] == "a@rail.uz"
    assert detail["phone_e164"] == PHONE
    assert detail["language"] == "uz"
    assert detail["need_summary"] == "Нужна интеграция POS с 1С"
    assert detail["owner_mode"] == "paused"
    assert detail["tg_username"] is None

    # Повторный запрос того же человека — не вторая карточка, а заметка в первой.
    again = client.post("/api/v1/leads/web", json=web_body(live_settings, text="Ещё: сроки?"))
    assert again.status_code == 202
    assert again.json()["lead_id"] == lead_id
    async with sessions() as session:
        notes = (await session.scalars(select(LeadNote.text))).all()
        leads = (await session.scalars(select(Lead.id))).all()
    assert notes == ["[web] Ещё: сроки?"]
    assert leads == [lead_id]

    # Honeypot: принято, но лида нет.
    trap = client.post("/api/v1/leads/web", json=web_body(live_settings, website="http://spam"))
    assert trap.status_code == 202
    assert trap.json() == {"lead_id": None}

    # Слишком быстрое заполнение и без контактов — единый формат ошибок ADR-0017.
    fast = client.post(
        "/api/v1/leads/web", json=web_body(live_settings, form_token=form_token(live_settings, 0))
    )
    assert fast.status_code == 422
    assert fast.json()["details"] == {"reason": "form_too_fast", "field": "form_token"}
    none = client.post("/api/v1/leads/web", json=web_body(live_settings, phone=None, email=None))
    assert none.status_code == 422
    assert none.json()["details"]["reason"] == "contact_required"

    actions = await audit_actions(sessions)
    assert {"lead.create_web", "lead.web_request"} <= actions


async def test_web_form_consent_required_and_stored(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """Q-12 (M2-CAB-03): `consent: true` обязательно; у нового лида — `consent_given_at`, аудит."""
    without = web_body(live_settings)
    without.pop("consent")
    # `false` и поле, не переданное вовсе, — один подкод.
    for body in (web_body(live_settings, consent=False), without):
        refused = client.post("/api/v1/leads/web", json=body)
        assert refused.status_code == 422
        assert refused.json()["code"] == "validation_failed"
        assert refused.json()["details"] == {"reason": "consent_required", "field": "consent"}
    async with sessions() as session:
        assert (await session.scalars(select(Lead.id))).all() == []

    accepted = client.post("/api/v1/leads/web", json=web_body(live_settings))
    assert accepted.status_code == 202, accepted.text
    lead_id = accepted.json()["lead_id"]
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.consent_given_at is not None
        assert lead.consent_version == "web-form"
        created = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "lead.create_web"))
        ).one()
    assert created.after is not None
    assert created.after["consent_version"] == "web-form"
    assert created.after["consent_given_at"] == lead.consent_given_at.isoformat()

    # Существующая карточка без согласия (ручной лид по звонку) — согласие формы не переносится
    # в карточку (у Telegram-лида это открыло бы обработку диалога ИИ), а пишется в аудит.
    manager, password = await make_user(sessions, "consent-mgr@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)
    manual = client.post(
        "/api/v1/leads",
        json={"source": "phone", "name": "Бобур", "phone": "+998907654321"},
        headers=auth,
    )
    assert manual.status_code == 201, manual.text
    repeat = client.post(
        "/api/v1/leads/web",
        json=web_body(live_settings, phone="+998907654321", email=None, text="Перезвоните"),
    )
    assert repeat.json()["lead_id"] == manual.json()["id"]
    async with sessions() as session:
        known = await session.get(Lead, manual.json()["id"])
        assert known is not None
        assert known.consent_given_at is None
        logged = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "lead.web_request"))
        ).one()
    assert logged.after is not None
    assert logged.after["repeat"] is True
    assert logged.after["consent_version"] == "web-form"


async def test_web_form_rate_limit_per_ip(client: TestClient, live_settings: Settings) -> None:
    for _ in range(5):
        assert client.post("/api/v1/leads/web", json=web_body(live_settings)).status_code == 202
    blocked = client.post("/api/v1/leads/web", json=web_body(live_settings))
    assert blocked.status_code == 429
    assert blocked.json() == {
        "code": "rate_limited",
        "message": "too many requests from this address",
        "details": {"reason": "rate_limited"},
    }


async def test_manual_lead_roles_and_duplicates(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "mgr@railtech.uz", ["manager"])
    viewer, _ = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    body = {
        "source": "phone",
        "name": "Бобур",
        "company": "Logistics LLC",
        "phone": "+998 90 765-43-21",
        "need": "Узнать цену на POS",
    }
    assert client.post("/api/v1/leads", json=body).status_code == 401
    assert (
        client.post("/api/v1/leads", json=body, headers=login(client, viewer.email, password))
    ).status_code == 403

    auth = login(client, manager.email, password)
    created = client.post("/api/v1/leads", json=body, headers=auth)
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]
    inbox = client.get("/api/v1/inbox", headers=auth).json()
    assert [lead["id"] for lead in inbox["mine"]] == [lead_id]
    detail = client.get(f"/api/v1/leads/{lead_id}", headers=auth).json()
    assert (detail["source"], detail["stage"], detail["owner_mode"]) == (
        "phone",
        "in_progress",
        "human",
    )
    assert detail["assigned_user_id"] == manager.id
    assert detail["phone_e164"] == "+998907654321"
    assert detail["company_name"] == "Logistics LLC"

    duplicate = client.post("/api/v1/leads", json={**body, "name": "Другой"}, headers=auth)
    assert duplicate.status_code == 409
    assert duplicate.json()["details"] == {
        "reason": "lead_exists",
        "lead_id": lead_id,
        "display_name": "Бобур",
        "field": "phone",
    }

    async with sessions() as session, session.begin():
        row = Client(name="ООО Клиент")
        session.add(row)
        await session.flush()
        session.add(ClientContact(client_id=row.id, full_name="К", phone_e164="+998911111111"))
        client_id = row.id
    known = client.post(
        "/api/v1/leads",
        json={"source": "referral", "name": "Знакомый", "phone": "+998911111111"},
        headers=auth,
    )
    assert known.status_code == 409
    assert known.json()["details"] == {
        "reason": "client_exists",
        "client_id": client_id,
        "client_name": "ООО Клиент",
        "field": "phone",
    }

    no_email = client.post(
        "/api/v1/leads", json={"source": "email", "name": "Без почты"}, headers=auth
    )
    assert no_email.status_code == 422
    assert no_email.json()["details"] == {"reason": "contact_required", "field": "email"}

    async with sessions() as session:
        moves = (await session.scalars(select(StageTransition))).all()
    assert [(m.from_stage, m.to_stage, m.source, m.reason) for m in moves] == [
        ("new", "in_progress", "user", "created manually")
    ]
    assert "lead.create" in await audit_actions(sessions)


async def test_telegram_lead_merges_into_web_lead_by_phone(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """Лид с сайта (раньше) + Telegram-лид в передаче (позже) → одна карточка после номера."""
    web_id = client.post("/api/v1/leads/web", json=web_body(live_settings)).json()["lead_id"]
    tg_id = await escalated_lead(sessions, tg_user_id=5001)
    assert tg_id != web_id
    refreshed: list[int] = []

    async def on_card_changed(escalation_id: int) -> None:
        refreshed.append(escalation_id)

    bot = ClientBotService(
        sessions, SettingsService(sessions, ttl_s=0), on_card_changed=on_card_changed
    )
    await bot.save_phone(5001, PHONE)

    async with sessions() as session:
        leads = (await session.scalars(select(Lead).order_by(Lead.id))).all()
        identity = (await session.scalars(select(TelegramIdentity))).one()
        conversation = (await session.scalars(select(Conversation))).one()
        escalation = (await session.scalars(select(Escalation))).one()
        moves = (await session.scalars(select(StageTransition))).all()
        merge_audit = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "lead.merge"))
        ).one()
    assert [lead.id for lead in leads] == [web_id]
    survivor = leads[0]
    assert (survivor.source, survivor.stage, survivor.owner_mode) == ("web", "handoff", "paused")
    assert survivor.display_name == "Алишер"
    assert survivor.company_name == "ООО Рельс"
    assert survivor.phone_e164 == PHONE
    assert survivor.consent_given_at is not None
    assert (identity.lead_id, identity.phone_e164, identity.tg_user_id) == (web_id, PHONE, 5001)
    assert conversation.lead_id == web_id
    assert (escalation.lead_id, escalation.status) == (web_id, "open")
    assert [(m.from_stage, m.to_stage, m.source) for m in moves] == [("new", "handoff", "system")]
    assert merge_audit.entity_id == str(web_id)
    assert merge_audit.before is not None
    assert merge_audit.after is not None
    assert merge_audit.before["absorbed"]["id"] == tg_id
    assert set(merge_audit.after["moved"]) >= {
        "telegram_identities",
        "conversations",
        "escalations",
    }
    assert refreshed == [escalation.id]

    manager, password = await make_user(sessions, "merge@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)
    history = client.get(f"/api/v1/leads/{web_id}/messages", headers=auth).json()
    assert [m["text"] for m in history] == ["Сколько стоит?"]
    detail = client.get(f"/api/v1/leads/{web_id}", headers=auth).json()
    assert (detail["source"], detail["tg_username"], detail["phone_e164"]) == (
        "web",
        "aziz",
        PHONE,
    )
    assert client.get(f"/api/v1/leads/{tg_id}", headers=auth).status_code == 404
    inbox = client.get("/api/v1/inbox", headers=auth).json()
    assert [lead["id"] for lead in inbox["escalations"]] == [web_id]
    # Лид на паузе без ответственного виден и в «Без ответственного» — как любая передача.
    assert [lead["id"] for lead in inbox["unassigned"]] == [web_id]


async def test_phone_without_match_merges_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    tg_id = await escalated_lead(sessions, tg_user_id=5002)
    bot = ClientBotService(sessions, SettingsService(sessions, ttl_s=0))
    await bot.save_phone(5002, "+998933333333")
    async with sessions() as session:
        identity = (await session.scalars(select(TelegramIdentity))).one()
        leads = (await session.scalars(select(Lead.id))).all()
    assert (identity.lead_id, identity.phone_e164) == (tg_id, "+998933333333")
    assert leads == [tg_id]
    assert "lead.merge" not in await audit_actions(sessions)
