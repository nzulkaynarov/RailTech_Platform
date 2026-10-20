"""`GET /leads/{id}`: клиент лида в ERP и состояние его передачи (FIX-34b, Q-FIX34-1)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.clients import Client
from app.models.leads import Lead
from tests.integration.crm_helpers import escalated_lead, login, make_user

pytestmark = pytest.mark.integration


async def _bind_client(
    sessions: async_sessionmaker[AsyncSession],
    lead_id: int,
    *,
    erp_company_id: int | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    async with sessions() as session, session.begin():
        client = Client(
            name="ООО Ромашка",
            erp_company_id=erp_company_id,
            erp_handoff_status=status,
            erp_handoff_error=error,
        )
        session.add(client)
        await session.flush()
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.stage, lead.client_id = "customer", client.id


async def test_lead_without_client_is_not_in_erp(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=5101)
    manager, password = await make_user(sessions, "in-erp-1@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        detail = http.get(f"/api/v1/leads/{lead_id}", headers=login(http, manager.email, password))
    body = detail.json()
    assert detail.status_code == 200
    assert body["client_in_erp"] is False
    assert (body["client_handoff_status"], body["client_handoff_error"]) == (None, None)


@pytest.mark.parametrize(
    ("erp_company_id", "status", "error", "in_erp"),
    [
        (None, None, None, False),  # стал клиентом в режиме local: статуса нет
        (None, "pending", None, False),
        (None, "pending", "ErpUnavailable", False),
        (None, "failed", "inn_conflict", False),
        (77, "done", None, True),
        (77, None, None, True),  # привязан ERP-событием, без передачи из CRM
    ],
)
async def test_client_in_erp_follows_company_id_and_state_is_passed_through(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    erp_company_id: int | None,
    status: str | None,
    error: str | None,
    in_erp: bool,
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=5102)
    await _bind_client(sessions, lead_id, erp_company_id=erp_company_id, status=status, error=error)
    manager, password = await make_user(sessions, "in-erp-2@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        body = http.get(
            f"/api/v1/leads/{lead_id}", headers=login(http, manager.email, password)
        ).json()
    assert body["client_in_erp"] is in_erp
    assert body["erp_company_id"] == erp_company_id
    assert (body["client_handoff_status"], body["client_handoff_error"]) == (status, error)


async def test_lead_detail_requires_login(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    lead_id = await escalated_lead(sessions, tg_user_id=5103)
    await _bind_client(sessions, lead_id, erp_company_id=77, status="done")
    with TestClient(create_app(live_settings)) as http:
        assert http.get(f"/api/v1/leads/{lead_id}").status_code == 401
