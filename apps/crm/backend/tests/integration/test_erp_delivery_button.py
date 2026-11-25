"""Кнопка «Кабинет» у событий поставки ведёт на сделку, в том числе в языковых вариантах."""

from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.settings_base import LANGUAGES
from tests.integration.bus_harness import ERP_DEAL, Harness
from tests.integration.test_request_accepted_notice import CABINET, set_cabinet

pytestmark = pytest.mark.integration


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Harness]:
    stand = Harness(sessions)
    yield stand
    stand.close()


@pytest.mark.parametrize("event", ["delivery.status_changed", "delivery.eta_changed"])
async def test_delivery_button_opens_the_deal_in_the_sent_message_and_in_every_variant(
    harness: Harness, sessions: async_sessionmaker[AsyncSession], event: str
) -> None:
    await set_cabinet(sessions)
    client_id, _ = await harness.seed_client()
    event_id = await harness.store(event, client_id)

    assert await harness.process(event_id) == "processed"

    expected = f"{CABINET}/deals/{ERP_DEAL}"
    assert harness.bot.markups[0].inline_keyboard[-1][-1].url == expected
    notice = await harness.notice(event_id)
    assert notice is not None
    [item] = [i for i in notice.items if i["kind"] == "client"]
    assert item["buttons"][-1][1] == expected
    assert set(item["variants"]) == set(LANGUAGES)
    for variant in item["variants"].values():
        assert variant["buttons"][-1][1] == expected
