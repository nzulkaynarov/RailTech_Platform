"""Снятая зависшая задача «повтор опасен»: строка получает правдивый статус (ЗАВИС-1)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.notice_errors import error_text
from app.models.email import EmailLog
from app.models.leads import Lead
from app.models.notices import ClientNotice
from app.models.qualification import Escalation
from app.repositories.leads import add_message, open_conversation
from app.tasks.stalled_hooks import (
    fail_client_notice,
    reopen_escalation_reminder,
    reopen_web_lead_reminder,
)
from tests.integration.crm_helpers import escalated_lead

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
STARTED = datetime.now(UTC) - timedelta(minutes=5)  # старт прерванной задачи


async def _notice(sessions: Sessions, lead_id: int, channel: str = "telegram") -> int:
    async with sessions() as session, session.begin():
        notice = ClientNotice(
            kind="web_confirmation", lead_id=lead_id, channel=channel, status="queued"
        )
        session.add(notice)
        await session.flush()
        return notice.id


async def _get(sessions: Sessions, notice_id: int) -> ClientNotice:
    async with sessions() as session:
        notice = await session.get(ClientNotice, notice_id)
    assert notice is not None
    return notice


async def test_an_email_notice_without_a_letter_is_failed_and_can_be_repeated(
    sessions: Sessions,
) -> None:
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id, channel="email")

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    notice = await _get(sessions, notice_id)
    assert (notice.status, notice.error) == ("failed", "interrupted")


async def test_an_email_notice_whose_letter_is_already_logged_stays_queued_and_linked(
    sessions: Sessions,
) -> None:
    """Окно: письмо записано в журнал, а связь с ним ещё нет: не говорим «не отправлено»."""
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id, channel="email")
    async with sessions() as session, session.begin():
        letter = EmailLog(
            to_email="a@rail.uz",
            subject="s",
            template="web_confirmation",
            lang="ru",
            status="queued",
            ref_kind="client_notice",
            ref_id=str(notice_id),
        )
        session.add(letter)
        await session.flush()
        letter_id = letter.id

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    notice = await _get(sessions, notice_id)
    assert (notice.status, notice.error, notice.email_log_id) == ("queued", None, letter_id)


async def test_a_telegram_notice_with_no_trace_is_unconfirmed_without_a_call_to_repeat(
    sessions: Sessions,
) -> None:
    """Окно: сообщение могло уйти до остановки, а след записать не успели — повтор был бы вторым."""
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id)

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    notice = await _get(sessions, notice_id)
    assert (notice.status, notice.error) == ("failed", "delivery_unconfirmed")
    assert "повтор" in (error_text(notice.error) or "")
    assert "Повторите" not in (error_text(notice.error) or "")


async def test_a_telegram_notice_with_the_message_in_the_conversation_is_sent(
    sessions: Sessions,
) -> None:
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id)
    async with sessions() as session, session.begin():
        conversation = await open_conversation(session, lead_id)
        assert conversation is not None
        await add_message(
            session,
            conversation_id=conversation.id,
            role="bot",
            text="Спасибо",
            meta={"notice": "web_confirmation"},
        )

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    notice = await _get(sessions, notice_id)
    assert (notice.status, notice.error) == ("sent", None)
    assert notice.sent_at is not None


async def test_an_older_confirmation_does_not_count_for_a_new_notice(sessions: Sessions) -> None:
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        conversation = await open_conversation(session, lead_id)
        assert conversation is not None
        await add_message(
            session,
            conversation_id=conversation.id,
            role="bot",
            text="Спасибо",
            meta={"notice": "web_confirmation"},
        )
    notice_id = await _notice(sessions, lead_id)

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    assert (await _get(sessions, notice_id)).error == "delivery_unconfirmed"


async def test_a_sent_notice_is_left_alone(sessions: Sessions) -> None:
    lead_id = await escalated_lead(sessions)
    notice_id = await _notice(sessions, lead_id)
    async with sessions() as session, session.begin():
        (await session.get(ClientNotice, notice_id)).status = "sent"  # type: ignore[union-attr]

    await fail_client_notice(sessions, {"notice_id": notice_id}, None)

    async with sessions() as session:
        assert (await session.get(ClientNotice, notice_id)).status == "sent"  # type: ignore[union-attr]


async def test_the_web_lead_reminder_mark_is_cleared_so_the_sweep_repeats_it(
    sessions: Sessions,
) -> None:
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        (await session.get(Lead, lead_id)).first_response_notified_at = datetime.now(UTC)  # type: ignore[union-attr]

    await reopen_web_lead_reminder(sessions, {"lead_id": lead_id}, STARTED)

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

    await reopen_escalation_reminder(sessions, {"escalation_id": escalation_id}, STARTED)

    async with sessions() as session:
        assert (await session.get(Escalation, escalation_id)).sla_notified_at is None  # type: ignore[union-attr]
    assert queued == [escalation_id]


async def test_a_reminder_mark_set_before_the_interrupted_run_is_kept(sessions: Sessions) -> None:
    """Отметку поставил другой проход (периодический) до старта прерванной задачи — не трогаем."""
    lead_id = await escalated_lead(sessions)
    earlier = STARTED - timedelta(minutes=10)
    async with sessions() as session, session.begin():
        (await session.get(Lead, lead_id)).first_response_notified_at = earlier  # type: ignore[union-attr]

    await reopen_web_lead_reminder(sessions, {"lead_id": lead_id}, STARTED)

    async with sessions() as session:
        assert (await session.get(Lead, lead_id)).first_response_notified_at == earlier  # type: ignore[union-attr]


async def test_an_escalation_mark_set_before_the_interrupted_run_is_kept(
    sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead_id = await escalated_lead(sessions)
    earlier = STARTED - timedelta(minutes=10)
    async with sessions() as session, session.begin():
        escalation = (
            await session.scalars(select(Escalation).where(Escalation.lead_id == lead_id))
        ).one()
        escalation.sla_notified_at = earlier
        escalation_id = escalation.id
    queued: list[int] = []

    from app.tasks import notify

    async def defer_async(**kwargs: int) -> None:
        queued.append(kwargs["escalation_id"])

    monkeypatch.setattr(notify.escalation_sla_check, "defer_async", defer_async)

    await reopen_escalation_reminder(sessions, {"escalation_id": escalation_id}, STARTED)

    async with sessions() as session:
        assert (await session.get(Escalation, escalation_id)).sla_notified_at == earlier  # type: ignore[union-attr]
    assert queued == []
