"""Сделка закрывается вместе с лидом в одной транзакции; выигранная — финал (ADR-0019)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.models.deals import Deal
from app.schemas.deals import DealCreate, DealUpdate
from app.schemas.settings import DealsSettings
from app.security.principal import Principal
from app.services import deals
from app.services.conversation import ConversationService
from tests.integration.test_customer import service
from tests.integration.test_lifecycle import escalated_prospect, manager
from tests.unit.agents.fakes import ReplayModel

pytestmark = pytest.mark.integration
__all__ = ["service"]
CFG = DealsSettings()


async def all_deals(sessions: async_sessionmaker[AsyncSession]) -> list[Deal]:
    async with sessions() as session:
        return list((await session.scalars(select(Deal))).all())


async def test_won_lead_creates_won_deal_with_amount(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await escalated_prospect(sessions, service[0])
    who, leads = await manager(sessions)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "won", None, amount=Decimal("1500000"))

    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.lead_id, deal.amount, deal.currency) == (
        "won",
        lead_id,
        Decimal("1500000.00"),
        "UZS",
    )
    assert deal.closed_at is not None


async def test_lost_lead_marks_open_deal_lost_with_reason(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await escalated_prospect(sessions, service[0])
    who, leads = await manager(sessions)
    async with sessions() as session, session.begin():
        await deals.create(session, who, DealCreate(title="Вагоны", lead_id=lead_id), CFG)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "lost", "клиент передумал", lost_reason="Дорого")

    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.lost_reason) == ("lost", "Дорого")


async def test_won_deal_is_final_for_manager_but_not_admin(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, _ = await manager(sessions)
    admin = Principal(who.user_id, "Админ", ("admin",))
    async with sessions() as session, session.begin():
        deal_id = await deals.create(session, who, DealCreate(title="Ремонт"), CFG)
        await deals.update(session, who, deal_id, DealUpdate(stage="won"), CFG)
    with pytest.raises(ConflictError):
        async with sessions() as session, session.begin():
            await deals.update(session, who, deal_id, DealUpdate(stage="open"), CFG)
    async with sessions() as session, session.begin():
        await deals.update(session, admin, deal_id, DealUpdate(stage="open"), CFG)
    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.closed_at) == ("open", None)
