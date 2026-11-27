"""Снятая зависшая задача «повтор опасен»: строка получает правдивый статус (ЗАВИС-1)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.leads import Lead
from app.models.notices import ClientNotice
from app.models.qualification import Escalation
from app.tasks.stalled_hooks import (
    fail_client_notice,
    reopen_escalation_reminder,
    reopen_web_lead_reminder,
)
from tests.integration.crm_helpers import escalated_lead

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]


async def _notice(sessions: Sessions, lead_id: int, **fields: object) -> int:
    async with sessions() as session, session.begin():
        notice = ClientNotice(
            kind="web_confirmation", lead_id=lead_id, channel="telegram", status="queued", **fields
        )
        session.add(notice)
        await session.flush()
        return notice.id


async def test_a_queued_notice_becomes_failed_with_a_reason(sessions: Sessions) -> None:
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id)

    await fail_client_notice(sessions, {"notice_id": notice_id})

    async with sessions() as session:
        notice = await session.get(ClientNotice, notice_id)
    assert notice is not None
    assert (notice.status, notice.error) == ("failed", "interrupted")


async def test_a_sent_notice_is_left_alone(sessions: Sessions) -> None:
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id)
    async with sessions() as session, session.begin():
        (await session.get(ClientNotice, notice_id)).status = "sent"  # type: ignore[union-attr]

    await fail_client_notice(sessions, {"notice_id": notice_id})

    async with sessions() as session:
        assert (await session.get(ClientNotice, notice_id)).status == "sent"  # type: ignore[union-attr]


async def test_the_web_lead_reminder_mark_is_cleared_so_the_sweep_repeats_it(
    sessions: Sessions,
) -> None:
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        (await session.get(Lead, lead_id)).first_response_notified_at = datetime.now(UTC)  # type: ignore[union-attr]

    await reopen_web_lead_reminder(sessions, {"lead_id": lead_id})

    async with sessions() as session:
        assert (await session.get(Lead, lead_id)).first_response_notified_at is None  # type: ignore[union-attr]


async def test_the_escalation_reminder_mark_is_cleared_and_the_check_requeued(
    sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        escalation = (
            await session.scalars(select(Escalation).where(Escalation.lead_id == lead_id))
        ).one()
        escalation.sla_notified_at = datetime.now(UTC) - timedelta(minutes=1)
        escalation_id = escalation.id
    queued: list[int] = []

    from app.tasks import notify

    async def defer_async(**kwargs: int) -> None:
        queued.append(kwargs["escalation_id"])

    monkeypatch.setattr(notify.escalation_sla_check, "defer_async", defer_async)

    await reopen_escalation_reminder(sessions, {"escalation_id": escalation_id})

    async with sessions() as session:
        assert (await session.get(Escalation, escalation_id)).sla_notified_at is None  # type: ignore[union-attr]
    assert queued == [escalation_id]
