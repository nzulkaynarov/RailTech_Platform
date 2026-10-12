"""Запись в переписку без хода агента (аудит 2026-10-12): менеджер видит всё, что видел клиент."""

import pytest
from sqlalchemy import select

from app.models.leads import Message
from app.services.conversation import Outgoing
from tests.integration.test_conversation import USER, Stack, consented, msg, stack

pytestmark = pytest.mark.integration
__all__ = ["stack"]


async def rows(stack: Stack) -> list[tuple[str, str, dict[str, object]]]:
    async with stack.sessions() as session:
        result = await session.execute(
            select(Message.role, Message.text, Message.meta).order_by(Message.id)
        )
        return [(role, text, meta) for role, text, meta in result.all()]


async def test_files_are_accepted_only_after_consent(stack: Stack) -> None:
    assert await stack.service.accepts_files(USER) is False  # лида ещё нет
    await stack.service.start(msg("/start", language_code="ru"))
    assert await stack.service.accepts_files(USER) is False  # нет согласия
    await stack.service.accept_consent(USER)
    assert await stack.service.accepts_files(USER) is True


async def test_silenced_message_is_saved_without_reply(stack: Stack) -> None:
    await consented(stack)
    before = len(await rows(stack))
    lead_id = await stack.service.record_lead_message(msg("ещё"), meta={"rate_limited": True})
    assert lead_id is not None
    after = await rows(stack)
    assert len(after) == before + 1
    assert after[-1][0] == "lead"
    assert after[-1][2] == {"rate_limited": True}
    assert stack.model.requests == []


async def test_unknown_user_message_is_not_recorded(stack: Stack) -> None:
    before = await rows(stack)  # фикстура KB может засеять чужие сообщения
    assert await stack.service.record_lead_message(msg("привет")) is None
    assert await rows(stack) == before


async def test_handler_replies_are_saved_as_bot(stack: Stack) -> None:
    await consented(stack)
    before = len(await rows(stack))
    persisted = Outgoing("уже в БД", message_id=1)
    await stack.service.record_bot_replies(USER, [Outgoing("Телефон: +998"), persisted])
    after = await rows(stack)
    assert len(after) == before + 1
    assert after[-1][:2] == ("bot", "Телефон: +998")


async def test_language_switch_confirmation_is_saved(stack: Stack) -> None:
    await consented(stack)
    out = await stack.service.set_language(USER, "en")
    assert (await rows(stack))[-1][:2] == ("bot", out[0].text)
