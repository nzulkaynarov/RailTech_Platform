"""Зеркальная сделка ERP: сумму, стадию и прочее, чем владеет бэк-офис, в CRM не правят (I-26)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.deals import Deal
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration


async def _deal(
    sessions: async_sessionmaker[AsyncSession], *, erp_deal_id: int | None, stage: str = "open"
) -> int:
    async with sessions() as session, session.begin():
        deal = Deal(
            title="Заявка: Ромашка",
            amount=Decimal("1000.00"),
            currency="UZS",
            stage=stage,
            erp_deal_id=erp_deal_id,
            external_stage="quoting" if erp_deal_id else None,
        )
        session.add(deal)
        await session.flush()
        return deal.id


async def _session_of(sessions: async_sessionmaker[AsyncSession], deal_id: int) -> Deal:
    async with sessions() as session:
        deal = await session.get(Deal, deal_id)
    assert deal is not None
    return deal


@pytest.mark.parametrize(
    ("change", "fields"),
    [
        ({"amount": "5"}, ["amount"]),
        ({"currency": "USD"}, ["currency"]),
        ({"stage": "won"}, ["stage"]),
        ({"stage": "lost", "lost_reason": "Дорого"}, ["lost_reason", "stage"]),
        ({"title": "Другое название"}, ["title"]),
    ],
)
async def test_erp_owned_fields_of_a_mirror_deal_are_409_for_manager_and_admin(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    change: dict[str, str],
    fields: list[str],
) -> None:
    deal_id = await _deal(sessions, erp_deal_id=22)
    manager, manager_password = await make_user(sessions, "mirror-m@railtech.uz", ["manager"])
    admin, admin_password = await make_user(sessions, "mirror-a@railtech.uz", ["admin"])
    with TestClient(create_app(live_settings)) as http:
        for who, password in ((manager, manager_password), (admin, admin_password)):
            response = http.patch(
                f"/api/v1/deals/{deal_id}", json=change, headers=login(http, who.email, password)
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body["code"] == "conflict"
            assert body["details"] == {"reason": "deal_owned_by_erp", "fields": fields}
    deal = await _session_of(sessions, deal_id)
    assert (deal.title, deal.amount, deal.currency, deal.stage) == (
        "Заявка: Ромашка",
        Decimal("1000.00"),
        "UZS",
        "open",
    )


async def test_crm_fields_of_a_mirror_deal_stay_editable(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    deal_id = await _deal(sessions, erp_deal_id=22)
    manager, password = await make_user(sessions, "mirror-m2@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "mirror-c2@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        response = http.patch(
            f"/api/v1/deals/{deal_id}",
            json={
                "owner_user_id": colleague.id,
                "expected_close_date": "2026-12-01",
                "product_key": "wagons",
                # форма шлёт поля целиком: те же значения, что в зеркале, — не правка
                "amount": "1000",
                "currency": "UZS",
                "stage": "open",
            },
            headers=login(http, manager.email, password),
        )
    assert response.status_code == 200, response.text
    deal = await _session_of(sessions, deal_id)
    assert (deal.owner_user_id, str(deal.expected_close_date), deal.product_key) == (
        colleague.id,
        "2026-12-01",
        "wagons",
    )
    assert deal.amount == Decimal("1000.00")


async def test_local_deal_without_erp_is_still_fully_editable(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    deal_id = await _deal(sessions, erp_deal_id=None)
    manager, password = await make_user(sessions, "mirror-m3@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as http:
        response = http.patch(
            f"/api/v1/deals/{deal_id}",
            json={"amount": "5", "currency": "USD", "stage": "lost", "lost_reason": "Дорого"},
            headers=login(http, manager.email, password),
        )
    assert response.status_code == 200, response.text
    deal = await _session_of(sessions, deal_id)
    assert (deal.amount, deal.currency, deal.stage) == (Decimal("5.00"), "USD", "lost")
