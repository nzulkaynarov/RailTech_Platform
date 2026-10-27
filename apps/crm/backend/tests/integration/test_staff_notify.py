"""Личные уведомления (Q-010) на реальной БД: менеджер по своему лиду с троттлингом, админы."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.platform_links import LinkBase
from app.models.auth import User
from app.models.leads import Lead
from app.services.staff_notifier import StaffNotifier
from tests.integration.crm_helpers import FakeSender, escalated_lead, make_user

pytestmark = pytest.mark.integration
WINDOW = timedelta(minutes=5)


async def link(sessions: async_sessionmaker[AsyncSession], user_id: int, tg: int) -> None:
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == user_id).values(tg_user_id=tg))


async def test_manager_dm_once_per_window(sessions: async_sessionmaker[AsyncSession]) -> None:
    manager, _ = await make_user(sessions, "m@x.uz", ["manager"])
    tg = 7001
    await link(sessions, manager.id, tg)
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(owner_mode="human", assigned_user_id=manager.id)
        )
    bot = FakeSender()
    notifier = StaffNotifier(sessions, bot)
    now = datetime.now(UTC)
    old = LinkBase(platform=None, crm="https://crm.example.com")
    assert await notifier.lead_message(lead_id, now, WINDOW, old)
    assert not await notifier.lead_message(lead_id, now + timedelta(minutes=1), WINDOW, old)
    assert await notifier.lead_message(lead_id, now + WINDOW, WINDOW, old)
    assert [chat for chat, _ in bot.sent] == [tg, tg]
    assert f"https://crm.example.com/leads/{lead_id}" in bot.sent[0][1]
    assert "Сколько стоит?" in bot.sent[0][1]


async def test_no_dm_when_unsubscribed(sessions: async_sessionmaker[AsyncSession]) -> None:
    manager, _ = await make_user(sessions, "u@x.uz", ["manager"])
    await link(sessions, manager.id, 7002)
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == manager.id).values(notify_leads=False))
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(owner_mode="human", assigned_user_id=manager.id)
        )
    bot = FakeSender()
    assert not await StaffNotifier(sessions, bot).lead_message(
        lead_id, datetime.now(UTC), WINDOW, LinkBase(None, "x")
    )
    assert bot.sent == []


async def test_alert_reaches_subscribed_admin(sessions: async_sessionmaker[AsyncSession]) -> None:
    admin, _ = await make_user(sessions, "owner@x.uz", ["admin"])
    tg = 7001
    await link(sessions, admin.id, tg)
    bot = FakeSender()
    assert await StaffNotifier(sessions, bot).alert_admins("⚠️ тест", "test") >= 1
    assert (tg, "⚠️ тест") in bot.sent


async def test_handover_dm_links_to_the_platform(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    manager, _ = await make_user(sessions, "h@x.uz", ["manager"])
    await link(sessions, manager.id, 7003)
    lead_id = await escalated_lead(sessions)
    bot = FakeSender()
    links = LinkBase(platform="https://platform.example.com", crm="https://crm.example.com")
    assert await StaffNotifier(sessions, bot).handed_over(lead_id, manager.id, links)
    text = bot.sent[0][1]
    assert (
        f"platform.example.com/crm/leads?lead=L-{lead_id:04d}&amp;panel=open&amp;tab=card" in text
    )
    assert "crm.example.com" not in text
