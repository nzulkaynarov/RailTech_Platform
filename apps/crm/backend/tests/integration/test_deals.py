"""Сделка закрывается вместе с лидом в одной транзакции; выигранная — финал (ADR-0019)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.models.deals import Deal
from app.models.leads import Lead
from app.schemas.deals import DealCreate, DealUpdate
from app.schemas.settings_deals import DealsSettings
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
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        await deals.ensure_open_deal(session, lead)  # Q-021: идемпотентно, одна открытая
        await deals.ensure_open_deal(session, lead)
    await leads.take(who, lead_id)
    await leads.close(who, lead_id, "lost", "клиент передумал", lost_reason="Дорого")

    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.lost_reason) == ("lost", "Дорого")
    # сводка дашборда группирует отказы по причине (регрессия: GroupingError в PostgreSQL)
    async with sessions() as session:
        report = await deals.summary(session, 30, datetime.now(UTC))
    assert report.lost_count == 1
    assert [r.reason for r in report.lost_by_reason] == ["Дорого"]
    # ряд по дням без пропусков: отказ — в последнем дне (сегодня по Ташкенту)
    assert len(report.daily) in (30, 31)
    assert (report.daily[-1].won, report.daily[-1].lost) == (0, 1)
    assert sum(d.lost for d in report.daily) == 1


async def test_won_deal_is_final_for_manager_but_not_admin(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, _ = await manager(sessions)
    admin = Principal(who.user_id, "Админ", ("admin",))
    async with sessions() as session, session.begin():
        deal_id = await deals.create(session, who, DealCreate(title="Ремонт"), CFG)
        await deals.update(session, who, deal_id, DealUpdate(stage="won"), CFG)
    # выигрыш без суммы считается отдельно: дашборд не выдаёт частичную сумму за полную
    async with sessions() as session:
        report = await deals.summary(session, 30, datetime.now(UTC))
    assert (report.won_count, report.won_without_amount) == (1, 1)
    with pytest.raises(ConflictError):
        async with sessions() as session, session.begin():
            await deals.update(session, who, deal_id, DealUpdate(stage="open"), CFG)
    async with sessions() as session, session.begin():
        await deals.update(session, admin, deal_id, DealUpdate(stage="open"), CFG)
    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.closed_at) == ("open", None)


@pytest.mark.parametrize(
    "change",
    [
        {"amount": "1"},
        {"currency": "USD"},
        {"title": "Другое название"},
        {"expected_close_date": None},
    ],
)
async def test_any_edit_of_won_deal_by_manager_is_409(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
    change: dict[str, object],
) -> None:
    """Аудит P0-3: не только смена стадии — любая правка выигранной сделки менеджером."""
    who, _ = await manager(sessions)
    async with sessions() as session, session.begin():
        deal_id = await deals.create(session, who, DealCreate(title="Ремонт"), CFG)
        await deals.update(session, who, deal_id, DealUpdate(stage="won"), CFG)
    with pytest.raises(ConflictError) as caught:
        async with sessions() as session, session.begin():
            await deals.update(session, who, deal_id, DealUpdate.model_validate(change), CFG)
    assert caught.value.details["reason"] == "deal_won_final"


async def test_lost_lead_without_open_deal_creates_lost_deal(
    service: tuple[ConversationService, ReplayModel, list[str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Q-021: отказ без открытой сделки — проигранная сделка с причиной (аналитика отказов)."""
    lead_id = await escalated_prospect(sessions, service[0])
    who, leads = await manager(sessions)
    await leads.take(who, lead_id)
    async with sessions() as session, session.begin():
        await session.execute(delete(Deal))  # квалификация могла открыть сделку
    await leads.close(who, lead_id, "lost", None, lost_reason="Дорого")
    [deal] = await all_deals(sessions)
    assert (deal.stage, deal.lost_reason, deal.lead_id) == ("lost", "Дорого", lead_id)
