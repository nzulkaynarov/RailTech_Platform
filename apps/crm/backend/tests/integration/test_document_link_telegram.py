"""Код и личная ссылка документа в Telegram получателя (ДК-4): событие ERP."""

import dataclasses
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rt_bus import Event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import build_bus
from app.services.contact_telegram import ContactTelegramService
from app.services.document_link_telegram import (
    DOCUMENT_LINK_REQUESTED,
    DocumentLinkTelegramDelivery,
)
from tests.integration.test_contact_telegram import (
    USER,
    chat,
    contact,
    service,  # noqa: F401 — фикстура
    unlink_event,
)
from tests.unit.test_contact_link import BEFORE, token

pytestmark = pytest.mark.integration
# ruff: noqa: F811, PT018, PT011

CODE = "483920"
URL = "http://cabinet.localhost/d/personal-token-123"


@pytest.fixture(autouse=True)
def _bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    runtime.set_bus(build_bus(sessions, None))
    yield
    runtime.set_bus(None)


class RecordingBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[int, str, Any]] = []
        self._error = error

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append((chat_id, text, kwargs.get("reply_markup")))


def delivery(
    sessions: async_sessionmaker[AsyncSession], bot: RecordingBot
) -> Callable[[Event], Awaitable[str]]:
    async def provider() -> Any:
        return bot

    return DocumentLinkTelegramDelivery(sessions, provider).deliver


def code_event(
    client_id: int, contact_id: int, *, expires_in: timedelta = timedelta(minutes=10)
) -> Event:
    event = unlink_event(client_id, contact_id)
    event.data["payload"].update(
        language="ru",
        kind="code",
        document_kind="invoice",
        code=CODE,
        expires_at=(datetime.now(UTC) + expires_in).isoformat(),
    )
    return dataclasses.replace(event, type=DOCUMENT_LINK_REQUESTED, id=str(uuid.uuid4()))


def link_event(client_id: int, contact_id: int, **payload: Any) -> Event:
    event = unlink_event(client_id, contact_id)
    event.data["payload"].update(
        language="uz",
        kind="link",
        document_kind="invoice",
        number="INV-1",
        seller_name="ООО Продавец",
        url=URL,
    )
    event.data["payload"].update(payload)
    return dataclasses.replace(event, type=DOCUMENT_LINK_REQUESTED, id=str(uuid.uuid4()))


async def linked(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> tuple[int, int]:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    await service.bind(USER, token(contact=contact_id), BEFORE)
    return client_id, contact_id


async def test_the_code_goes_to_the_contacts_own_telegram_and_names_no_document(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id = await linked(sessions, service)
    bot = RecordingBot()

    outcome = await delivery(sessions, bot)(code_event(client_id, contact_id))

    assert outcome == "processed"
    ((chat_id, text, markup),) = bot.sent
    assert chat_id == USER and CODE in text and "10" in text and markup is None
    assert text == f"Код для входа: {CODE}. Действует 10 мин. Никому его не сообщайте."
    # в сообщении нет ни вида, ни номера, ни продавца, ни ссылки
    assert not any(word in text for word in ("INV-1", "Счёт", "Договор", "ООО", "http"))


async def test_the_code_is_not_sent_to_an_unlinked_or_foreign_contact_or_after_expiry(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    await chat(sessions, USER)
    client_id, contact_id = await contact(sessions)
    other_client, _ = await contact(sessions, "ООО Бета")
    bot = RecordingBot()
    deliver = delivery(sessions, bot)

    assert await deliver(code_event(client_id, contact_id)) == "skipped"  # Telegram не привязан
    await service.bind(USER, token(contact=contact_id), BEFORE)
    assert (
        await deliver(code_event(other_client, contact_id)) == "skipped"
    )  # контакт другого клиента
    assert (
        await deliver(code_event(client_id, contact_id, expires_in=timedelta(seconds=-5)))
        == "skipped"
    )
    assert bot.sent == []


async def test_the_link_goes_with_one_button_to_the_personal_link(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id = await linked(sessions, service)
    bot = RecordingBot()

    outcome = await delivery(sessions, bot)(link_event(client_id, contact_id))

    assert outcome == "processed"
    ((chat_id, text, markup),) = bot.sent
    assert chat_id == USER
    assert text == "Sizga hujjat yuborildi: Hisob INV-1, ООО Продавец."
    (row,) = markup.inline_keyboard
    (button,) = row
    assert button.url == URL
    assert button.text == "Hujjatni oçiş"
    assert URL not in text


async def test_a_link_that_is_not_http_is_not_sent(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id = await linked(sessions, service)
    bot = RecordingBot()

    assert (
        await delivery(sessions, bot)(link_event(client_id, contact_id, url="javascript:alert(1)"))
        == "skipped"
    )
    assert bot.sent == []


async def test_network_failure_is_raised_for_redelivery_and_a_refusal_is_not(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id = await linked(sessions, service)

    with pytest.raises(RuntimeError):
        await delivery(sessions, RecordingBot(TimeoutError()))(code_event(client_id, contact_id))


async def test_a_broken_event_reports_no_secret(
    sessions: async_sessionmaker[AsyncSession], service: ContactTelegramService
) -> None:
    client_id, contact_id = await linked(sessions, service)
    event = code_event(client_id, contact_id)
    event.data["payload"]["kind"] = "nonsense"

    with pytest.raises(ValueError) as caught:
        await delivery(sessions, RecordingBot())(event)

    assert CODE not in str(caught.value) and caught.value.__cause__ is None
