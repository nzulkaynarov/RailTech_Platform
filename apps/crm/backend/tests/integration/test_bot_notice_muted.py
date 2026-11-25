"""FX-9: бот CRM не пишет контакту, отключившему группу уведомлений в кабинете ERP."""

from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.leads import Lead, TelegramIdentity
from app.services.settings import SettingsService
from tests.integration.bus_harness import T0, Harness, data_for, event_type_of

pytestmark = pytest.mark.integration


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Harness]:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def second_account(
    sessions: async_sessionmaker[AsyncSession], client_id: int, tg_user_id: int
) -> None:
    async with sessions() as session, session.begin():
        session.add(TelegramIdentity(tg_user_id=tg_user_id, client_id=client_id, tg_first_name="B"))


async def deliver(harness: Harness, event: str, client_id: int, muted: list[int] | None) -> None:
    data = data_for(event, client_id)
    if muted is not None:
        data["telegram_muted_user_ids"] = muted
    event_id = await harness.receive(event_type_of(event), data, time=T0, event_id=None)
    assert await harness.process(event_id) == "processed"


async def test_muted_account_is_skipped_others_still_get_it(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=777)
    await second_account(sessions, client_id, 888)

    await deliver(harness, "invoice.paid", client_id, [777])

    assert [chat for chat, *_ in harness.bot.sent] == [888]


async def test_without_the_field_everyone_gets_it(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=777)
    await second_account(sessions, client_id, 888)

    await deliver(harness, "invoice.paid", client_id, None)

    assert sorted(chat for chat, *_ in harness.bot.sent) == [777, 888]


async def test_each_contact_gets_the_text_in_the_language_of_their_own_lead(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Бот пишет контакту на его языке, а не на языке лида компании, написавшего последним."""
    await SettingsService(sessions, ttl_s=0).update(
        "company",
        {"name": "RailTech", "crm_base_url": "http://x", "cabinet_url": "https://cabinet.example"},
        None,
        None,
    )
    client_id, _ = await harness.seed_client(tg_user_id=777)  # лид компании — русский
    async with sessions() as session, session.begin():
        own = Lead(display_name="B", stage="customer", owner_mode="bot", language="uz")
        session.add(own)
        await session.flush()
        session.add(
            TelegramIdentity(tg_user_id=888, client_id=client_id, lead_id=own.id, tg_first_name="B")
        )

    await deliver(harness, "invoice.paid", client_id, None)

    texts = dict(harness.bot.sent)
    assert set(texts) == {777, 888}
    assert texts[777] != texts[888]  # узбекский контакт не получает русский текст
    # кнопки — на языке контакта и ведут на точную страницу объекта в кабинете (УВ-2)
    buttons = {
        chat: [(b.text, b.url) for row in markup.inline_keyboard for b in row]
        for (chat, _), markup in zip(harness.bot.sent, harness.bot.markups, strict=True)
    }
    assert buttons[777][-1][0] == "Кабинет"
    assert buttons[888][-1][0] == "Kabinet"
    assert buttons[777][-1][1] == buttons[888][-1][1]
    assert buttons[777][-1][1].startswith("https://cabinet.example/invoices?focus=")
