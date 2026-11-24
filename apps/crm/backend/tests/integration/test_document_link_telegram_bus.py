"""Код и ссылка документа в Telegram через настоящий приёмник шины (ДК-4): секреты нигде не оседают.

`document_link.telegram_requested.v1`: `payload.code` и `payload.url` в inbox — маска `***`;
значения ищутся по содержимому во всех таблицах и в логах. Повтор того же id — `duplicate`,
второго сообщения нет; сбой сети — 503 без секрета в логе.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.document_link_telegram import DOCUMENT_LINK_REQUESTED
from tests.integration.bus_harness import Harness
from tests.integration.test_erp_acceptance_code import add_contact, everything_stored
from tests.integration.test_erp_seam_events import seeded

pytestmark = pytest.mark.integration
# ruff: noqa: PT018

CODE = "913557"
TOKEN = "personal-link-marker"
URL = f"http://cabinet.localhost/d/{TOKEN}"
TG_CONTACT = 4343


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Any:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def envelope_of(harness: Harness, kind: str) -> dict[str, Any]:
    envelope, client_id, _ = await seeded(harness, DOCUMENT_LINK_REQUESTED, tg_user_id=777)
    contact_id = await add_contact(harness, client_id, "Иван Петров", tg_user_id=TG_CONTACT)
    payload: dict[str, Any] = {
        "erp_contact_id": 310,
        "crm_contact_id": contact_id,
        "language": "ru",
        "kind": kind,
        "document_kind": "invoice",
    }
    if kind == "code":
        payload.update(
            code=CODE, expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        )
    else:
        payload.update(url=URL, number="INV-1", seller_name="ООО Продавец")
    envelope["data"]["payload"] = payload
    return envelope


def secret_of(kind: str) -> tuple[str, str]:
    """(поле payload, значение секрета)."""
    return ("code", CODE) if kind == "code" else ("url", URL)


@pytest.mark.parametrize("kind", ["code", "link"])
async def test_the_secret_is_masked_in_the_inbox_and_stored_nowhere(
    harness: Harness, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    envelope = await envelope_of(harness, kind)
    field, secret = secret_of(kind)
    caplog.set_level(logging.DEBUG)

    result = await harness.post(envelope)

    assert (result.status_code, result.body["status"]) == (200, "processed"), result.body
    assert [chat for chat, _ in harness.bot.sent] == [TG_CONTACT]
    async with harness.sessions() as session:
        stored = (
            await session.execute(
                text("SELECT envelope FROM rt_bus_inbox WHERE event_id = :id"),
                {"id": uuid.UUID(envelope["id"])},
            )
        ).scalar_one()
    assert stored["data"]["payload"][field] == "***", "в inbox лежит маска"
    dump = await everything_stored(harness)
    assert secret not in dump
    assert TOKEN not in dump and CODE not in dump
    assert secret not in caplog.text and TOKEN not in caplog.text and CODE not in caplog.text
    assert harness.enqueued == [], "через очередь секрет не идёт"


@pytest.mark.parametrize("kind", ["code", "link"])
async def test_the_link_message_has_one_button_and_the_code_message_none(
    harness: Harness, kind: str
) -> None:
    await harness.post(await envelope_of(harness, kind))
    (markup,) = harness.bot.markups
    if kind == "link":
        assert markup.inline_keyboard[0][0].url == URL
    else:
        assert markup is None


@pytest.mark.parametrize("kind", ["code", "link"])
async def test_a_redelivery_of_the_same_id_is_a_duplicate_without_a_second_message(
    harness: Harness, kind: str
) -> None:
    envelope = await envelope_of(harness, kind)
    first = await harness.post(envelope)
    assert first.body["status"] == "processed"

    again = await harness.post(envelope)

    assert (again.status_code, again.body["status"]) == (200, "duplicate")
    assert len(harness.bot.sent) == 1


@pytest.mark.parametrize("kind", ["code", "link"])
async def test_a_network_failure_is_503_and_the_secret_is_not_logged(
    harness: Harness, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    _, secret = secret_of(kind)
    harness.bot.fail_with = TelegramNetworkError(
        method=SendMessage(chat_id=1, text=f"x {secret}"), message=f"text {secret}"
    )
    envelope = await envelope_of(harness, kind)
    caplog.set_level(logging.DEBUG)

    result = await harness.post(envelope)

    assert result.status_code == 503, result.body
    assert harness.bot.sent == []
    assert secret not in caplog.text and TOKEN not in caplog.text and CODE not in caplog.text
    assert secret not in json.dumps(result.body)
    assert secret not in await everything_stored(harness)
