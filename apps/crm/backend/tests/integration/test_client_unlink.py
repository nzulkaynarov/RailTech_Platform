"""Отвязка последнего Telegram клиента и закрытие запроса с его эскалацией (аудит 2026-10-12)."""

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.clients import ServiceRequest
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.security.principal import Principal
from app.services.clients import ClientService
from tests.integration.crm_helpers import escalated_lead, make_user

pytestmark = pytest.mark.integration
TG = 7310


async def _customer(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int, Principal]:
    """Выигранный лид, которого сделали клиентом (как «Сделать клиентом» в CRM)."""
    lead_id = await escalated_lead(sessions, tg_user_id=TG)
    admin, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    who = Principal(admin.id, "Босс", ("admin",))
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.stage = "won"
        await session.execute(
            update(Escalation).where(Escalation.lead_id == lead_id).values(status="closed")
        )
    client_id = await ClientService(sessions).make_customer(who, lead_id, None, "ООО Альфа")
    return lead_id, client_id, who


async def _open_codes(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(Escalation.reason_codes).where(Escalation.status == "open")
        )
        return sorted(codes[0] for codes in rows)


async def test_unlink_last_identity_clears_client_and_stage(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id, client_id, who = await _customer(sessions)
    await ClientService(sessions).unlink_identity(who, client_id, TG)
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
    assert lead is not None
    assert (lead.client_id, lead.stage) == (None, "won")


@pytest.mark.parametrize(
    ("codes", "closed_with_last"),
    [(["service_request"], True), (["service_request", "attachment_received"], False)],
)
async def test_close_request_closes_escalation_with_last_open_request(
    sessions: async_sessionmaker[AsyncSession], codes: list[str], closed_with_last: bool
) -> None:
    lead_id, client_id, who = await _customer(sessions)
    async with sessions() as session, session.begin():
        first = ServiceRequest(client_id=client_id, lead_id=lead_id, summary="Касса")
        second = ServiceRequest(client_id=client_id, lead_id=lead_id, summary="Принтер")
        session.add_all([first, second])
        session.add(Escalation(lead_id=lead_id, reason_codes=codes, priority="info"))
        await session.flush()
        ids = first.id, second.id
    clients = ClientService(sessions)
    await clients.close_service_request(who, ids[0], "Готово")
    assert await _open_codes(sessions) == [codes[0]]  # второй запрос ещё открыт
    await clients.close_service_request(who, ids[1], "Готово")
    assert await _open_codes(sessions) == ([] if closed_with_last else [codes[0]])
