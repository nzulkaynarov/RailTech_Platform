"""«Люди» (PL-1): поля лида в `GET /leads` — компания (колонка или ответ бота), наличие контактов,
запись показа контактов лида в журнал. Данные лида должны доходить до «Людей» целиком."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.qualifier.graph import QualifierResult
from app.config import Settings
from app.domain.qualification import LeadSignals, Qualification, QualifierOutput
from app.domain.qualifier_decision import QualifierDecision
from app.main import create_app
from app.models.leads import Lead, TelegramIdentity
from app.services.qualifier import _apply_decision
from tests.integration.crm_helpers import escalated_lead, login, make_user

pytestmark = pytest.mark.integration


def _flags(row: dict[str, Any]) -> tuple[bool, bool, bool]:
    return row["has_phone"], row["has_email"], row["has_telegram"]


def _decision(company: str | None) -> QualifierDecision:
    return QualifierDecision(
        stage_path=(),
        rejected_reason=None,
        qualification=Qualification(company=company),
        signals=LeadSignals(),
        need_summary="Нужны тормозные колодки",
        product_interest=(),
        score=10,
        bot_turns_without_progress=0,
        hits=(),
    )


async def _apply(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, company: str | None
) -> None:
    result = QualifierResult(
        output=QualifierOutput(
            intent="other", sentiment="neutral", proposed_stage="new", confidence=0.5
        ),
        model="m",
        cost_usd=None,
        trace_id=None,
        prompt_version="v",
    )
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        await _apply_decision(session, lead, _decision(company), result)


async def test_company_from_bot_fills_empty_company_name(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """G4: компания из квалификации бота записывается в `company_name`, пока поле пусто."""
    lead_id = await escalated_lead(sessions, tg_user_id=6101)
    await _apply(sessions, lead_id, "ООО Ромашка")
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.company_name == "ООО Ромашка"


async def test_company_from_bot_does_not_overwrite_typed_company(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=6102)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.company_name = "ООО Из формы"
    await _apply(sessions, lead_id, "ООО Ромашка")
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.company_name == "ООО Из формы"


async def test_list_reads_company_of_existing_row_from_qualification(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """G4, чтение: лид, записанный до правки (колонка пуста, ответ бота в квалификации), в
    списке и в карточке показывает компанию — миграции данных не нужно."""
    lead_id = await escalated_lead(sessions, tg_user_id=6103)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.qualification = {"company": "ООО Старый лид"}
        assert lead.company_name is None
    manager, password = await make_user(sessions, "people-1@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        headers = login(http, manager.email, password)
        listed = http.get("/api/v1/leads", headers=headers).json()["items"]
        detail = http.get(f"/api/v1/leads/{lead_id}", headers=headers).json()
    assert next(i for i in listed if i["id"] == lead_id)["company_name"] == "ООО Старый лид"
    assert detail["company_name"] == "ООО Старый лид"


async def test_list_tells_which_contacts_exist_without_values(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """G1: `has_phone` — и номер из кнопки бота, `has_telegram` — аккаунт, `has_email` — почта;
    значений контактов в списке нет."""
    bare = await escalated_lead(sessions, tg_user_id=6111)
    rich = await escalated_lead(sessions, tg_user_id=6112)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, rich)
        assert lead is not None
        lead.email = "a@b.example"
        identity = (
            await session.scalars(select(TelegramIdentity).where(TelegramIdentity.lead_id == rich))
        ).one()
        identity.phone_e164 = "+998901234567"
        # лид без Telegram: ручной, номер в самой карточке
        manual = Lead(display_name="Звонок", source="phone", phone_e164="+998900000000")
        session.add(manual)
        await session.flush()
        manual_id = manual.id
        other = (
            await session.scalars(select(TelegramIdentity).where(TelegramIdentity.lead_id == bare))
        ).one()
        other.phone_e164 = None
    manager, password = await make_user(sessions, "people-2@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        rows = {
            i["id"]: i
            for i in http.get("/api/v1/leads", headers=login(http, manager.email, password)).json()[
                "items"
            ]
        }
    assert _flags(rows[bare]) == (False, False, True)
    assert _flags(rows[rich]) == (True, True, True)
    assert _flags(rows[manual_id]) == (True, False, False)
    assert {"phone", "email"}.isdisjoint(rows[rich])


async def test_lead_reveal_is_audited_as_lead(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """G1: показ контактов лида пишется в журнал с типом `lead`; без `kind` — как раньше."""
    manager, password = await make_user(sessions, "people-3@railtech.uz", ["manager"])
    admin, admin_password = await make_user(sessions, "people-4@railtech.uz", ["admin"])
    with TestClient(create_app(live_settings)) as http:
        headers = login(http, manager.email, password)
        url = "/api/v1/audit/contact-reveal"
        lead_reveal = {"contact": "101", "name": "Борис Лид", "kind": "lead"}
        assert http.post(url, headers=headers, json=lead_reveal).status_code == 204
        assert (
            http.post(url, headers=headers, json={"contact": "7", "name": "X"}).status_code == 204
        )
        assert http.post(url, headers=headers, json={**lead_reveal, "kind": "x"}).status_code == 422
        page = http.get(
            "/api/v1/audit?action=contact.reveal", headers=login(http, admin.email, admin_password)
        ).json()
    kinds = {(i["entity_type"], i["entity_id"]) for i in page["items"]}
    assert kinds == {("lead", "101"), ("erp_contact", "7")}
