"""«Согласие получено»: сотрудник отмечает согласие лида, заведённого вручную (FIX-57, D-8).

И заявка, созданная передачей, — отдельно от поздних сделок лида (D-10).
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote
from app.security.principal import Principal
from app.services.erp_handoff import ErpHandoffService
from app.services.lead_consent import LeadConsentService
from tests.integration.crm_helpers import login, make_user
from tests.integration.test_handoff import FakeErpClient, Queue, _manager, _service

pytestmark = pytest.mark.integration
ACTION = "/api/v1/leads/{}/actions/record_consent"


async def _manual_lead(
    sessions: async_sessionmaker[AsyncSession], email: str, source: str = "phone"
) -> tuple[Principal, int]:
    """Лид, заведённый вручную (звонок), без согласия — как «Новый лид» в CRM."""
    who, lead_id = await _manager(sessions, email, consent_at=None, consent_version=None)
    async with sessions() as session, session.begin():
        row = await session.get(Lead, lead_id)
        assert row is not None
        row.source = source
    return who, lead_id


async def _lead(sessions: async_sessionmaker[AsyncSession], lead_id: int) -> Lead:
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    return lead


async def _consent_audit(sessions: async_sessionmaker[AsyncSession]) -> list[AuditLog]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditLog).where(AuditLog.action == "lead.consent_recorded").order_by(AuditLog.id)
        )
        return list(rows)


async def test_manual_lead_cannot_be_handed_off_until_staff_marks_consent_then_it_passes(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    who, lead_id = await _manual_lead(sessions, "consent1@example.com")
    queue = Queue(sessions)

    # Проверка FIX-34 остаётся: без согласия — 422 и ничего не меняется.
    with pytest.raises(ValidationFailedError) as exc_info:
        await _service(sessions, queue).make_customer(who, lead_id, None, "Звонок ООО")
    assert exc_info.value.details["reason"] == Reason.HANDOFF_NO_CONSENT.value

    before = datetime.now(UTC)
    assert await LeadConsentService(sessions).record(who, lead_id, "phone", "  Звонок 21.10  ")

    lead = await _lead(sessions, lead_id)
    assert lead.consent_given_at is not None
    assert lead.consent_given_at >= before
    assert (lead.consent_version, lead.consent_method) == ("manual", "phone")
    # Аудит: кто, когда, способ, комментарий.
    (entry,) = await _consent_audit(sessions)
    assert (entry.actor_user_id, entry.entity_id) == (who.user_id, str(lead_id))
    assert entry.before == {"consent_given_at": None}
    assert entry.after is not None
    assert entry.after["consent_method"] == "phone"
    assert entry.after["consent_version"] == "manual"
    assert entry.after["comment"] == "Звонок 21.10"
    assert entry.after["consent_given_at"] == lead.consent_given_at.isoformat()
    # Лента лида: заметка сотрудника.
    async with sessions() as session:
        note = (await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))).one()
    assert note.user_id == who.user_id
    assert "устно по телефону" in note.text
    assert "Звонок 21.10" in note.text

    # После отметки «Передать в бэк-офис» проходит и уходит в ERP со способом согласия «как есть».
    client_id = await _service(sessions, queue).make_customer(who, lead_id, None, "Звонок ООО")
    fake_erp = FakeErpClient(request_id=202)
    assert (
        await ErpHandoffService(sessions, fake_erp).run(client_id, lead_id, who.user_id) == "done"
    )
    sent = fake_erp.calls[0].consent
    assert sent.version == "manual"
    assert datetime.fromisoformat(sent.given_at) == lead.consent_given_at

    # D-10: заявка передачи запомнена на лиде; поздняя заявка клиента из Cabinet её не вытесняет.
    async with sessions() as session, session.begin():
        session.add(Deal(client_id=client_id, lead_id=lead_id, title="Из Cabinet", erp_deal_id=203))
    with TestClient(create_app(live_settings)) as http:
        manager, password = await make_user(sessions, "consent1-reader@example.com", ["manager"])
        detail = http.get(
            f"/api/v1/leads/{lead_id}", headers=login(http, manager.email, password)
        ).json()
    assert detail["erp_deal_id"] == 202
    assert detail["consent_method"] == "phone"
    assert detail["consent_given_at"] is not None
    assert (await _lead(sessions, lead_id)).erp_request_id == 202


async def test_repeated_mark_is_idempotent_and_keeps_the_first_consent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manual_lead(sessions, "consent2@example.com", "referral")
    service = LeadConsentService(sessions)

    assert await service.record(who, lead_id, "email", None) is True
    first = await _lead(sessions, lead_id)
    assert await service.record(who, lead_id, "paper", "другое") is False

    second = await _lead(sessions, lead_id)
    assert (second.consent_given_at, second.consent_method) == (first.consent_given_at, "email")
    assert len(await _consent_audit(sessions)) == 1
    async with sessions() as session:
        notes = (await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))).all()
    assert len(notes) == 1


async def test_telegram_lead_gives_consent_in_the_bot_not_by_staff(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(
        sessions, "consent-tg@example.com", consent_at=None, consent_version=None
    )  # источник по умолчанию — telegram

    with pytest.raises(ConflictError) as caught:
        await LeadConsentService(sessions).record(who, lead_id, "phone", None)

    assert caught.value.details["reason"] == "consent_via_bot"
    assert (await _lead(sessions, lead_id)).consent_given_at is None
    assert await _consent_audit(sessions) == []


async def test_consent_given_by_the_lead_himself_is_not_overwritten(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "consent3@example.com")  # согласие дано лидом

    assert await LeadConsentService(sessions).record(who, lead_id, "phone", None) is False

    lead = await _lead(sessions, lead_id)
    assert (lead.consent_version, lead.consent_method) == ("2026-10-08", None)
    assert await _consent_audit(sessions) == []


async def test_api_rights_and_errors(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    owner, lead_id = await _manual_lead(sessions, "consent-owner@example.com", "email")
    other, other_password = await make_user(sessions, "consent-other@example.com", ["manager"])
    admin, admin_password = await make_user(sessions, "consent-admin@example.com", ["admin"])
    viewer, viewer_password = await make_user(sessions, "consent-viewer@example.com", ["viewer"])
    del owner
    body = {"method": "paper", "comment": "Подписанное заявление"}
    with TestClient(create_app(live_settings)) as http:
        url = ACTION.format(lead_id)
        assert http.post(url, json=body).status_code == 401
        as_viewer = http.post(url, json=body, headers=login(http, viewer.email, viewer_password))
        assert as_viewer.status_code == 403
        as_other = http.post(url, json=body, headers=login(http, other.email, other_password))
        assert as_other.status_code == 403
        assert as_other.json()["details"]["reason"] == "not_lead_owner"
        admin_headers = login(http, admin.email, admin_password)
        assert http.post(url, json={"method": "fax"}, headers=admin_headers).status_code == 422
        assert (
            http.post(url, json={"method": "paper", "comment": "я" * 501}, headers=admin_headers)
        ).status_code == 422
        assert http.post(ACTION.format(9999), json=body, headers=admin_headers).status_code == 404
        assert (await _lead(sessions, lead_id)).consent_given_at is None

        ok = http.post(url, json=body, headers=admin_headers)
        assert (ok.status_code, ok.json()) == (200, {"ok": True, "recorded": True})
        again = http.post(url, json=body, headers=admin_headers)
        assert (again.status_code, again.json()["recorded"]) == (200, False)
    (entry,) = await _consent_audit(sessions)
    assert entry.actor_user_id == admin.id
    assert (await _lead(sessions, lead_id)).consent_method == "paper"
