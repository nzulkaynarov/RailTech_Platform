"""Долг клиента по валютам в карточке (шов 0.3.0, FIX-60): эндпоинт, права, сбой ERP."""

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.clients import Client
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

ERP = "https://erp.example"
SUMMARY = f"{ERP}/api/integration/v1/companies/118/summary"
BODY = {
    "erp_company_id": 118,
    "crm_client_id": 1,
    "name": "ООО Порядок",
    "open_deals": [],
    "receivables": {"amount": "100.00", "currency": "UZS"},
    "receivables_by_currency": [
        {"amount": "100.00", "currency": "UZS"},
        {"amount": "12.50", "currency": "USD"},
    ],
}


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(
        update={
            "secrets_key": SecretStr("k" * 64),
            "erp_base_url": ERP,
            "erp_service_token": SecretStr("integration-fake-service-token"),
        }
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        yield test_client


async def client_row(sessions: async_sessionmaker[AsyncSession], erp_company_id: int | None) -> int:
    async with sessions() as session, session.begin():
        row = Client(name="ООО Порядок", erp_company_id=erp_company_id)
        session.add(row)
        await session.flush()
        return row.id


async def auth(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


@respx.mock
async def test_manager_sees_the_debt_per_currency(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    client_id = await client_row(sessions, 118)
    headers = await auth(sessions, client, "manager")
    respx.get(SUMMARY).mock(return_value=httpx.Response(200, json=BODY))

    response = client.get(f"/api/v1/clients/{client_id}/erp-receivables", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "ok",
        "receivables": [
            {"amount": "100.00", "currency": "UZS"},
            {"amount": "12.50", "currency": "USD"},
        ],
        "reason": None,
        "retry_after_s": None,
    }


@respx.mock
async def test_the_card_stays_as_before_when_erp_has_no_field_or_fails(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    client_id = await client_row(sessions, 118)
    headers = await auth(sessions, client, "manager")
    url = f"/api/v1/clients/{client_id}/erp-receivables"
    route = respx.get(SUMMARY)

    route.mock(
        return_value=httpx.Response(
            200, json={k: v for k, v in BODY.items() if k != "receivables_by_currency"}
        )
    )
    old = client.get(url, headers=headers)
    route.mock(return_value=httpx.Response(500))
    broken = client.get(url, headers=headers)
    route.mock(return_value=httpx.Response(429, headers={"Retry-After": "20"}))
    limited = client.get(url, headers=headers)

    assert (old.status_code, old.json()["status"], old.json()["reason"]) == (
        200,
        "unavailable",
        "no_data",
    )
    assert (broken.status_code, broken.json()["status"]) == (200, "unavailable")
    assert (limited.status_code, limited.json()["reason"], limited.json()["retry_after_s"]) == (
        200,
        "rate_limited",
        20,
    )
    # сама карточка клиента открывается как раньше
    assert client.get(f"/api/v1/clients/{client_id}", headers=headers).status_code == 200


async def test_a_client_not_in_erp_has_no_block_and_no_erp_call(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    client_id = await client_row(sessions, None)
    headers = await auth(sessions, client, "manager")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(SUMMARY)
        response = client.get(f"/api/v1/clients/{client_id}/erp-receivables", headers=headers)
    assert response.json()["reason"] == "not_linked"
    assert not route.called


async def test_unknown_client_is_404_and_anonymous_is_401(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    headers = await auth(sessions, client, "manager")
    assert client.get("/api/v1/clients/9999/erp-receivables", headers=headers).status_code == 404
    assert client.get("/api/v1/clients/1/erp-receivables").status_code == 401
