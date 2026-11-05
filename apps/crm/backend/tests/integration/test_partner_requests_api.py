"""Решение менеджера по партнёру ERP в карточке клиента (PART-CRM): API CRM.

Партнёр ERP, похожий на существующего клиента, ждёт подтверждения: `GET /clients/{id}` отдаёт
ждущие заявки (`partner_requests`), `POST …/partner-requests/{id}/confirm|decline` решают их.
Чтение — любому, кто видит клиентов; решение — тому, кто их правит (читатель получает 403).
"""

import copy
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.clients import Client, ClientContact, PartnerClientRequest
from tests.bus_events import example_data
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

REQUESTED = "uz.railtech.erp.partner.client_requested.v1"


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def _pending(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with sessions() as session, session.begin():
        row = Client(name="ООО Рельс", inn="301234567")
        session.add(row)
        await session.flush()
        payload = copy.deepcopy(example_data(REQUESTED))
        request = PartnerClientRequest(
            client_id=row.id, erp_company_id=214, matched_by="inn", payload=payload
        )
        session.add(request)
        await session.flush()
        return row.id, request.id


async def test_card_lists_the_pending_request_and_confirm_links_the_client(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, request_id = await _pending(sessions)
    manager, password = await make_user(sessions, "partner-confirm@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)

    card = client.get(f"/api/v1/clients/{client_id}", headers=auth).json()
    [pending] = card["partner_requests"]
    assert (pending["id"], pending["erp_company_id"], pending["matched_by"]) == (
        request_id,
        214,
        "inn",
    )
    assert pending["company_name"] == "Демо Мануфактуринг ООО"
    assert pending["contacts"] == [
        {"full_name": "Иванов Пётр", "email": "ivanov@manufacturing.example"}
    ]

    url = f"/api/v1/clients/{client_id}/partner-requests/{request_id}/confirm"
    assert client.post(url, headers=auth).status_code == 200
    assert client.post(url, headers=auth).status_code == 404, "решённая заявка — нет"
    card = client.get(f"/api/v1/clients/{client_id}", headers=auth).json()
    assert card["erp_company_id"] == 214
    assert card["partner_requests"] == []
    async with sessions() as session:
        emails = (await session.scalars(select(ClientContact.email))).all()
    assert list(emails) == ["ivanov@manufacturing.example"]


async def test_decline_creates_a_new_client_and_returns_its_id(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, request_id = await _pending(sessions)
    manager, password = await make_user(sessions, "partner-decline@railtech.uz", ["manager"])
    auth = login(client, manager.email, password)

    response = client.post(
        f"/api/v1/clients/{client_id}/partner-requests/{request_id}/decline", headers=auth
    )

    assert response.status_code == 201
    new_id = response.json()["id"]
    assert new_id != client_id
    card = client.get(f"/api/v1/clients/{new_id}", headers=auth).json()
    assert card["erp_company_id"] == 214
    old = client.get(f"/api/v1/clients/{client_id}", headers=auth).json()
    assert old["erp_company_id"] is None
    assert old["partner_requests"] == []


async def test_viewer_sees_the_request_but_cannot_decide(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, request_id = await _pending(sessions)
    viewer, password = await make_user(sessions, "partner-viewer@railtech.uz", ["viewer"])
    auth = login(client, viewer.email, password)

    card = client.get(f"/api/v1/clients/{client_id}", headers=auth)
    assert card.status_code == 200
    assert len(card.json()["partner_requests"]) == 1
    base = f"/api/v1/clients/{client_id}/partner-requests/{request_id}"
    assert client.post(f"{base}/confirm", headers=auth).status_code == 403
    assert client.post(f"{base}/decline", headers=auth).status_code == 403
    assert client.post(f"{base}/confirm").status_code == 401
