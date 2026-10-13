"""Дашборд: таблица менеджеров и доля SLA на реальном PostgreSQL; песочница не считается."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.leads import Lead
from app.models.qualification import Escalation
from app.services import dashboard
from tests.integration.crm_helpers import escalated_lead, make_user

pytestmark = pytest.mark.integration


async def _take(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, user_id: int | None, minutes: int
) -> None:
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Escalation)
            .where(Escalation.lead_id == lead_id)
            .values(
                created_at=now - timedelta(minutes=60),
                sla_due_at=now - timedelta(minutes=30),
                taken_at=now - timedelta(minutes=60 - minutes) if user_id else None,
                taken_by_user_id=user_id,
                status="taken" if user_id else "open",
            )
        )
        if user_id:
            lead = await session.scalar(select(Lead).where(Lead.id == lead_id))
            assert lead is not None
            lead.assigned_user_id = user_id


async def test_managers_and_sla(sessions: async_sessionmaker[AsyncSession]) -> None:
    anna, _ = await make_user(sessions, "anna@railtech.uz", ["manager"])
    fast = await escalated_lead(sessions, 6001)
    slow = await escalated_lead(sessions, 6002)
    missed = await escalated_lead(sessions, 6003)
    sandbox = await escalated_lead(sessions, 6004)
    await _take(sessions, fast, anna.id, 10)  # в срок (SLA — 30 мин)
    await _take(sessions, slow, anna.id, 50)  # позже срока
    await _take(sessions, missed, None, 0)  # не забрали, срок прошёл
    await _take(sessions, sandbox, anna.id, 5)
    async with sessions() as session, session.begin():
        await session.execute(update(Lead).where(Lead.id == sandbox).values(source="sandbox"))
    today = datetime.now(UTC).date()
    async with sessions() as session:
        board = await dashboard.build(session, 7, today, "UTC")
    [row] = board.managers
    assert (row.user_id, row.taken, row.median_take_minutes) == (anna.id, 2, 30.0)
    assert row.active_leads == 2
    assert board.sla is not None
    assert (board.sla.due, board.sla.met, board.sla.share) == (3, 1, 0.3333)
