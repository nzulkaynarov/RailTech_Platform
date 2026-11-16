"""Имя Telegram-бота для ERP (`crm.bot.changed`): событие при новом имени и повтор при старте.

Один источник имени бота ансамбля — CRM: ERP и кабинет берут его из проекции, а не из своих
настроек (прод 2026-11-16: у ERP и кабинета имени не было, привязка Telegram и вход через бота
в кабинете не работали, хотя бот принимал лидов).
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.services.bot_publish import republish_bot
from app.services.bot_state import BotStateService

pytestmark = pytest.mark.integration

BOT_EVENT = "uz.railtech.crm.bot.changed.v1"


@pytest.fixture(autouse=True)
def _bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    runtime.set_bus(build_bus(sessions, None))
    yield
    runtime.set_bus(None)


async def _events(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :type ORDER BY created_at, id"),
            {"type": BOT_EVENT},
        )
        return [row["data"] for row in rows.scalars().all()]


async def _report(state: BotStateService, username: str | None, *, started: bool = False) -> None:
    await state.report(
        running=username is not None,
        mode="polling",
        source="settings",
        username=username,
        last_error=None,
        profile=None,
        started=started,
    )


async def test_new_bot_name_is_published_once_and_republished_on_start(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await republish_bot(sessions) is None, "бот ещё не запускался — публиковать нечего"
    state = BotStateService(sessions)

    await _report(state, None, started=True)
    assert await _events(sessions) == [], "бот без токена — имени нет"
    await _report(state, "railtech_demo_bot")
    await _report(state, "railtech_demo_bot")  # пульс с тем же именем
    await _report(state, None)  # сбой: имя не пропадает из проекции
    (event,) = await _events(sessions)
    assert event["username"] == "railtech_demo_bot"
    assert event["actor"] == {"type": "system"}

    await _report(state, "railtech_new_bot")  # токен сменили в «Подключениях»
    names = [e["username"] for e in await _events(sessions)]
    assert names == ["railtech_demo_bot", "railtech_new_bot"]

    assert await republish_bot(sessions) == "railtech_new_bot"
    assert (await _events(sessions))[-1]["username"] == "railtech_new_bot"
