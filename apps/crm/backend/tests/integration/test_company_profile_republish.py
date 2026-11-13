"""Профиль компании для ERP (задача «Н3a2»): событие при сохранении и повтор при старте."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.services.company_profile_publish import EPOCH, republish_company_profile
from app.services.settings import SettingsService

pytestmark = pytest.mark.integration

PROFILE_EVENT = "uz.railtech.crm.company_profile.changed.v1"


@pytest.fixture(autouse=True)
def _bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    runtime.set_bus(build_bus(sessions, None))
    yield
    runtime.set_bus(None)


async def _events(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = await session.execute(
            text("SELECT envelope FROM rt_bus_outbox WHERE type = :type ORDER BY created_at, id"),
            {"type": PROFILE_EVENT},
        )
        return [row["data"] for row in rows.scalars().all()]


async def test_republish_without_saved_setting_sends_the_default_from_the_epoch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await republish_company_profile(sessions)
    (event,) = await _events(sessions)
    assert event["changed_at"].startswith(EPOCH.strftime("%Y-%m-%d"))
    assert set(event) == {"name", "phone", "site", "address", "changed_at", "actor"}


async def test_saving_the_company_section_publishes_the_profile_in_the_same_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = SettingsService(sessions)
    current = (await service.get()).company.model_dump(mode="json")
    body = {**current, "name": "Новая Компания", "phone": "+998 71 1"}
    await service.update("company", body, None)
    (event,) = await _events(sessions)
    assert (event["name"], event["phone"]) == ("Новая Компания", "+998 71 1")
    assert await republish_company_profile(sessions) == "Новая Компания"
    first, again = await _events(sessions)
    assert again["changed_at"] == first["changed_at"], "повтор — со временем сохранения"
