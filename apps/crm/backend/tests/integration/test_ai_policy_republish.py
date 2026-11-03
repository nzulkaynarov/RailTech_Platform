"""Повтор публикации политики защиты данных для ИИ при старте воркера (PD-BIZ)."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.services.ai_policy_publish import EPOCH, republish_ai_policy, sync_ai_policy_on_start
from app.services.settings import SettingsService

pytestmark = pytest.mark.integration

POLICY_EVENT = "uz.railtech.crm.ai_policy.changed.v1"


@pytest.fixture(autouse=True)
def _bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    runtime.set_bus(build_bus(sessions, None))
    yield
    runtime.set_bus(None)


async def _events(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :type ORDER BY created_at, id"),
            {"type": POLICY_EVENT},
        )
        return [row["data"] for row in rows.scalars().all()]


async def test_republish_without_saved_setting_sends_default_from_the_epoch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await republish_ai_policy(sessions) == "business"
    (event,) = await _events(sessions)
    assert event["pii_policy"] == "business"
    assert event["changed_at"].startswith(EPOCH.strftime("%Y-%m-%d"))
    assert event["actor"] == {"type": "system"}


async def test_republish_repeats_the_saved_policy_with_its_save_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """«Строгая» сохранена до появления EDS: повтор несёт её и время сохранения."""
    await SettingsService(sessions).update("ai", {"pii_policy": "strict"}, None)
    saved = (await _events(sessions))[0]
    assert await republish_ai_policy(sessions) == "strict"
    assert await republish_ai_policy(sessions) == "strict"
    events = await _events(sessions)
    assert [e["pii_policy"] for e in events] == ["strict", "strict", "strict"]
    assert {e["changed_at"] for e in events} == {saved["changed_at"]}


async def test_start_never_fails_even_when_the_bus_is_broken(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object, **__: object) -> None:
        raise RuntimeError("bus is down")

    monkeypatch.setattr("app.services.ai_policy_publish.bus_events.ai_policy_changed", broken)
    await sync_ai_policy_on_start(sessions)  # сбой — в лог, воркер стартует
    assert await _events(sessions) == []
