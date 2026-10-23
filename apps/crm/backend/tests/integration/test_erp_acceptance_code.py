"""Код акцепта КП и контакты в исходах КП (шов 0.3.0, FIX-60 → B4; Q-FIX22-1, Q-FIX22-6).

`uz.railtech.erp.quote.acceptance_code_requested.v1`: бот присылает код контакту в Telegram;
`data.payload.code` не попадает в inbox шины (там маска `***`), в outbox, в очередь задач, в ленту
лида и в логи. Проверяется по СОДЕРЖИМОМУ: код — уникальная строка, её ищут во всех таблицах,
заметках и записях логов. `quote.accepted|rejected` показывают в ленте, какой контакт CRM принял КП.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.erp_event import CODE_TYPE
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from tests.bus_events import example_data, signed_raw
from tests.integration.bus_harness import Harness
from tests.integration.test_erp_seam_events import COMPANY, notes, receive, seeded

pytestmark = pytest.mark.integration

CODE = "739104"  # уникальная строка: ищем её везде, где её быть не должно
TG_PRIMARY = 777
TG_CONTACT = 4242
NOT_SENT = "erp_acceptance_code_not_sent"


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Any:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def add_contact(
    harness: Harness,
    client_id: int,
    name: str,
    *,
    tg_user_id: int | None = None,
    primary: bool = False,
) -> int:
    async with harness.sessions() as session, session.begin():
        identity_id = None
        if tg_user_id is not None:
            identity = TelegramIdentity(tg_user_id=tg_user_id, client_id=client_id)
            session.add(identity)
            await session.flush()
            identity_id = identity.id
        contact = ClientContact(
            client_id=client_id,
            full_name=name,
            telegram_identity_id=identity_id,
            is_primary=primary,
        )
        session.add(contact)
        await session.flush()
        return contact.id


async def code_envelope(
    harness: Harness, *, contact: str = "own", minutes: int = 15, language: str | None = None
) -> tuple[dict[str, Any], int, int]:
    """Конверт с кодом для клиента с контактом `contact`: `own` — свой Telegram, `primary` —
    основной контакт без привязки (Telegram клиента), `none` — без Telegram.
    """
    envelope, client_id, lead_id = await seeded(harness, CODE_TYPE, tg_user_id=TG_PRIMARY)
    if language:
        async with harness.sessions() as session, session.begin():
            lead = await session.get(Lead, lead_id)
            assert lead is not None
            lead.language = language
    if contact == "own":
        contact_id = await add_contact(harness, client_id, "Иван Петров", tg_user_id=TG_CONTACT)
    elif contact == "primary":
        contact_id = await add_contact(harness, client_id, "Иван Петров", primary=True)
    else:
        contact_id = await add_contact(harness, client_id, "Иван Петров")
    envelope["data"]["payload"].update(
        code=CODE,
        crm_contact_id=contact_id,
        expires_at=(datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
    )
    return envelope, client_id, lead_id


async def send_code(harness: Harness, envelope: dict[str, Any]) -> str:
    """Доставка с кодом через настоящий приёмник: inline-обработчик, ответ 200 `processed`."""
    result = await harness.post(envelope)
    assert (result.status_code, result.body["status"]) == (200, "processed"), result.body
    return str(envelope["id"])


async def everything_stored(harness: Harness) -> str:
    """Таблицы шины, лента, сообщения и очередь задач одним текстом: кода в нём быть не должно."""
    queries = (
        "SELECT * FROM rt_bus_inbox",
        "SELECT * FROM rt_bus_outbox",
        "SELECT * FROM rt_bus_delivery",
        "SELECT * FROM erp_event_notices",
        "SELECT text FROM lead_notes",
        "SELECT * FROM procrastinate_jobs",
    )
    dumped: list[list[str]] = []
    async with harness.sessions() as session:
        for query in queries:
            rows = (await session.execute(text(query))).all()
            dumped.append([str(list(map(str, row))) for row in rows])
    return json.dumps(dumped, default=str)


def reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Причины «код не отправлен» из записей лога доставки (structlog → stdlib)."""
    found: list[str] = []
    for record in caplog.records:
        message = record.getMessage()
        if NOT_SENT in message:
            match = re.search(r"'reason': '([^']*)'", message)
            found.append(match.group(1) if match else "")
    return found


# ── Доставка ────────────────────────────────────────────────────────────────────────────────────


async def test_the_code_goes_to_the_contact_in_telegram_and_nowhere_else(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, client_id, lead_id = await code_envelope(harness)
    caplog.set_level(logging.DEBUG)

    event_id = await send_code(harness, envelope)

    assert [chat for chat, _ in harness.bot.sent] == [TG_CONTACT], "контакту, а не основному"
    (_, text_) = harness.bot.sent[0]
    assert CODE in text_
    assert "15" in text_ or "14" in text_, "срок действия назван в минутах"
    assert envelope["data"]["deal"]["title"] in text_

    row = await harness.inbox(event_id)
    assert (row["status"], row["error"]) == ("processed", None)
    async with harness.sessions() as session:
        stored = (
            await session.execute(
                text("SELECT envelope FROM rt_bus_inbox WHERE event_id = :id"),
                {"id": uuid.UUID(event_id)},
            )
        ).scalar_one()
    assert stored["data"]["payload"]["code"] == "***", "в inbox лежит маска, не код"
    assert (
        stored["data"]["payload"]["crm_contact_id"] == envelope["data"]["payload"]["crm_contact_id"]
    )

    assert CODE not in await everything_stored(harness), (
        "кода нет ни в шине, ни в ленте, ни в очереди"
    )
    assert await notes(harness, lead_id) == []
    assert CODE not in caplog.text
    assert harness.enqueued == [], "через очередь код не идёт — её аргументы лежат в БД"
    assert client_id


async def test_an_unlinked_primary_contact_gets_the_code_on_the_client_telegram(
    harness: Harness,
) -> None:
    envelope, _, _ = await code_envelope(harness, contact="primary")
    await send_code(harness, envelope)
    assert [chat for chat, _ in harness.bot.sent] == [TG_PRIMARY]


@pytest.mark.parametrize(
    ("language", "needle"),
    [("ru", "Код подтверждения"), ("uz", "tasdiqlash kodi"), ("en", "Confirmation code")],
)
async def test_the_text_is_in_the_language_of_the_lead(
    harness: Harness, language: str, needle: str
) -> None:
    envelope, _, _ = await code_envelope(harness, language=language)
    await send_code(harness, envelope)
    (_, text_) = harness.bot.sent[0]
    assert needle in text_
    assert CODE in text_


async def test_a_contact_without_telegram_gets_nothing_and_the_log_says_why(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness, contact="none")
    caplog.set_level(logging.DEBUG)
    await send_code(harness, envelope)

    assert harness.bot.sent == []
    assert reasons(caplog) == ["contact has no telegram"]
    assert CODE not in await everything_stored(harness)


async def test_a_contact_of_another_client_is_refused(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness)
    stranger_client, _ = await harness.seed_client(erp_company_id=COMPANY + 5, tg_user_id=9001)
    envelope["data"]["payload"]["crm_contact_id"] = await add_contact(
        harness, stranger_client, "Чужой", tg_user_id=9002
    )
    caplog.set_level(logging.DEBUG)
    await send_code(harness, envelope)

    assert harness.bot.sent == [], "код не уходит контакту другого клиента"
    assert len(reasons(caplog)) == 1
    assert "not found" in reasons(caplog)[0]


async def test_an_event_of_another_company_is_refused(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness)
    envelope["data"]["erp_company_id"] = COMPANY + 1
    caplog.set_level(logging.DEBUG)
    await send_code(harness, envelope)
    assert harness.bot.sent == []
    assert reasons(caplog) == ["company mismatch"]


async def test_an_expired_code_is_not_sent(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness, minutes=-1)
    caplog.set_level(logging.DEBUG)
    await send_code(harness, envelope)
    assert harness.bot.sent == []
    assert reasons(caplog) == ["code already expired"]


async def test_without_a_running_bot_the_failure_is_logged_without_the_code(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.bot_available = False
    envelope, _, _ = await code_envelope(harness)
    caplog.set_level(logging.DEBUG)
    await send_code(harness, envelope)

    assert reasons(caplog) == ["bot is not running"]
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text


async def test_a_telegram_failure_is_logged_without_leaking_the_code(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def refuse(*_: Any, **__: Any) -> None:
        raise TelegramNetworkError(
            method=SendMessage(chat_id=1, text=f"code {CODE}"), message=f"text code {CODE}"
        )

    monkeypatch.setattr(harness.bot, "send_message", refuse)
    envelope, _, _ = await code_envelope(harness)
    caplog.set_level(logging.DEBUG)

    await send_code(harness, envelope)

    assert reasons(caplog) == ["telegram: TelegramNetworkError"]
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text


# ── Повторы ─────────────────────────────────────────────────────────────────────────────────────


async def test_the_same_event_id_is_a_duplicate_and_does_not_send_a_second_code(
    harness: Harness,
) -> None:
    envelope, _, _ = await code_envelope(harness)
    await send_code(harness, envelope)

    again = await harness.post(envelope)

    assert (again.status_code, again.body["status"]) == (200, "duplicate")
    assert len(harness.bot.sent) == 1


async def test_the_queue_and_the_sweepers_never_touch_a_code_event(harness: Harness) -> None:
    envelope, _, _ = await code_envelope(harness)
    event_id = await send_code(harness, envelope)

    assert await harness.bus.requeue_stuck_inbox(older_than=0) == 0
    assert await harness.notices.sweep() == 0
    assert await harness.process(event_id) == "processed"  # уже обработано: ничего нового
    assert harness.enqueued == []
    assert len(harness.bot.sent) == 1


# ── Тело, которое не разобралось, кода не уносит ────────────────────────────────────────────────


async def test_a_broken_code_event_is_refused_and_leaves_no_code_behind(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness)
    envelope["data"]["payload"].pop("expires_at")  # не по схеме → 422
    caplog.set_level(logging.DEBUG)

    result = await harness.post(envelope)

    assert (result.status_code, result.body) == (422, {"error": "invalid_data"})
    assert harness.bot.sent == []
    assert CODE not in json.dumps(result.body)
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text, "ошибка схемы не печатает значение секретного поля"


async def test_a_code_event_with_a_wrong_signature_is_refused_and_not_stored(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    envelope, _, _ = await code_envelope(harness)
    caplog.set_level(logging.DEBUG)

    result = await harness.post(envelope, secret="not-the-pair-secret")

    assert result.status_code == 401
    assert harness.bot.sent == []
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text


async def test_a_broken_json_of_a_code_event_is_not_kept_even_in_part(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    raw = f'{{"specversion": "1.0", "data": {{"payload": {{"code": "{CODE}"'.encode()  # оборван
    event_id = str(uuid.uuid4())
    headers = signed_raw(raw, event_id, harness.secret())
    caplog.set_level(logging.DEBUG)

    result = await harness.bus.receive(headers, raw)

    assert result.status_code == 400
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text


async def test_unknown_fields_in_a_code_event_do_not_break_it(harness: Harness) -> None:
    """Терпимый читатель (Q-FIX35-4): новое поле ERP не отказ и не дыра для кода."""
    envelope, _, _ = await code_envelope(harness)
    envelope["data"]["from_the_future"] = {"channel": "sms"}
    envelope["data"]["payload"]["channel_hint"] = "sms"
    event_id = await send_code(harness, envelope)

    assert [chat for chat, _ in harness.bot.sent] == [TG_CONTACT]
    assert (await harness.inbox(event_id))["status"] == "processed"
    assert CODE not in await everything_stored(harness)


# ── Исходы КП: кто принял ───────────────────────────────────────────────────────────────────────


async def test_the_feed_names_the_contact_who_accepted_the_quote(harness: Harness) -> None:
    envelope, client_id, lead_id = await seeded(harness, "uz.railtech.erp.quote.accepted.v1")
    envelope["data"]["payload"]["crm_contact_id"] = await add_contact(
        harness, client_id, "Иван Петров"
    )
    await harness.process(await receive(harness, envelope))

    (note,) = await notes(harness, lead_id)
    assert "Иван Петров" in note
    assert "акцептовал" in note
    assert f"#{envelope['data']['payload']['erp_quote_id']}" in note


async def test_the_feed_names_the_contact_who_rejected_the_quote_with_the_reason(
    harness: Harness,
) -> None:
    envelope, client_id, lead_id = await seeded(harness, "uz.railtech.erp.quote.rejected.v1")
    contact_id = await add_contact(harness, client_id, "Алия Каримова")
    envelope["data"]["payload"].update(crm_contact_id=contact_id, reason="Дорого")
    await harness.process(await receive(harness, envelope))

    (note,) = await notes(harness, lead_id)
    assert "Алия Каримова" in note
    assert "отклонено" in note
    assert "Дорого" in note


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("uz.railtech.erp.quote.accepted.v1", "Клиент акцептовал КП #1203 v2."),
        ("uz.railtech.erp.quote.rejected.v1", "КП #1203 v2 отклонено клиентом."),
    ],
)
async def test_without_a_crm_contact_the_feed_stays_neutral(
    harness: Harness, event_type: str, expected: str
) -> None:
    envelope, _, lead_id = await seeded(harness, event_type)
    payload = envelope["data"]["payload"]
    payload.pop("crm_contact_id", None)
    payload.pop("reason", None)
    payload["erp_contact_id"] = 311  # ERP контакт знает, CRM — нет
    await harness.process(await receive(harness, envelope))

    (note,) = await notes(harness, lead_id)
    assert note == expected


async def test_a_contact_of_another_client_is_never_named_in_the_feed(harness: Harness) -> None:
    other_client, _ = await harness.seed_client(erp_company_id=COMPANY + 7, tg_user_id=9100)
    stranger = await add_contact(harness, other_client, "Посторонний Контакт")
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.quote.accepted.v1")
    envelope["data"]["payload"]["crm_contact_id"] = stranger
    await harness.process(await receive(harness, envelope))

    (note,) = await notes(harness, lead_id)
    assert "Посторонний" not in note


async def test_viewing_the_quote_does_not_name_a_contact(harness: Harness) -> None:
    envelope, client_id, lead_id = await seeded(harness, "uz.railtech.erp.quote.viewed.v1")
    envelope["data"]["payload"]["crm_contact_id"] = await add_contact(
        harness, client_id, "Иван Петров"
    )
    await harness.process(await receive(harness, envelope))
    (note,) = await notes(harness, lead_id)
    assert "Иван Петров" not in note


async def test_client_row_is_not_changed_by_a_code_event(harness: Harness) -> None:
    envelope, client_id, _ = await code_envelope(harness)
    await send_code(harness, envelope)
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    assert client.erp_company_id == COMPANY


def test_the_example_of_the_contract_carries_a_code_that_is_not_a_real_one() -> None:
    assert example_data(CODE_TYPE)["payload"]["code"] == "000000"
