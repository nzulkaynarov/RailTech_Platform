"""Код акцепта КП и контакты в исходах КП (шов 0.3.0, FIX-60; Q-FIX22-1, Q-FIX22-6).

`quote.acceptance_code_requested`: бот присылает код контакту в Telegram; `payload.code` не
попадает в журнал `erp_incoming_events` (ни в `payload`, ни в `error`, ни в `outbox`), в ленту лида
и в логи. Проверяется по СОДЕРЖИМОМУ: код — уникальная строка, её ищут во всех строках журнала,
заметках и записях логов. `quote.accepted|rejected` показывают в ленте, какой контакт CRM принял КП.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.models.clients import Client, ClientContact
from app.models.integrations import ErpIncomingEvent
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.schemas.erp_events import CODE_EVENT, REDACTED
from tests.integration.test_erp_events import Harness
from tests.integration.test_erp_seam_events import COMPANY, deliver, notes, receive, seeded
from tests.seam_events import example_event

pytestmark = pytest.mark.integration

CODE = "739104"  # уникальная строка: ищем её везде, где её быть не должно
TG_PRIMARY = 777
TG_CONTACT = 4242


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Harness:
    return Harness(sessions)


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


async def code_body(
    harness: Harness, *, contact: str = "own", minutes: int = 15, language: str | None = None
) -> tuple[dict[str, Any], int, int]:
    """Тело события с кодом для клиента с контактом `contact`: `own` — свой Telegram, `primary` —
    основной контакт без привязки (Telegram клиента), `none` — без Telegram.
    """
    body, client_id, lead_id = await seeded(harness, CODE_EVENT, tg_user_id=TG_PRIMARY)
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
    body["payload"].update(
        code=CODE,
        crm_contact_id=contact_id,
        expires_at=(datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
    )
    return body, client_id, lead_id


async def send_code(harness: Harness, body: dict[str, Any], event_id: str | None = None) -> str:
    event_id = event_id or str(uuid.uuid4())
    raw = json.dumps(body).encode()
    result = await deliver(harness, event_id, body["event"], raw)
    assert result[0] is False
    return event_id


async def everything_stored(harness: Harness) -> str:
    """Журнал, заметки ленты и очередь задач одним текстом: кода в нём быть не должно."""
    async with harness.sessions() as session:
        rows = (await session.execute(select(ErpIncomingEvent))).scalars().all()
        dumped = [
            {
                column.name: str(getattr(row, column.name))
                for column in ErpIncomingEvent.__table__.columns
            }
            for row in rows
        ]
        texts = (await session.scalars(select(LeadNote.text))).all()
        jobs = (await session.execute(select_all_jobs())).all()
    return json.dumps([dumped, list(texts), [list(map(str, j)) for j in jobs]], default=str)


def select_all_jobs() -> Any:
    from sqlalchemy import text

    return text("select * from procrastinate_jobs")


# ── Доставка ────────────────────────────────────────────────────────────────────────────────────


async def test_the_code_goes_to_the_contact_in_telegram_and_nowhere_else(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    body, client_id, lead_id = await code_body(harness)
    caplog.set_level(logging.DEBUG)

    with capture_logs() as structured:
        event_id = await send_code(harness, body)

    assert [chat for chat, _ in harness.bot.sent] == [TG_CONTACT], "контакту, а не основному"
    (_, text) = harness.bot.sent[0]
    assert CODE in text
    assert "15" in text or "14" in text, "срок действия назван в минутах"
    assert body["deal"]["title"] in text

    row = await harness.row(event_id)
    assert (row.status, row.error, row.outbox) == ("processed", None, None)
    assert row.payload["payload"]["code"] == REDACTED
    assert row.payload["payload"]["crm_contact_id"] == body["payload"]["crm_contact_id"]
    assert (row.erp_company_id, row.crm_client_id) == (COMPANY, client_id)

    assert CODE not in await everything_stored(harness), "кода нет ни в журнале, ни в ленте"
    assert await notes(harness, lead_id) == []
    assert CODE not in caplog.text
    assert CODE not in json.dumps(structured, default=str)
    assert harness.enqueued == [], "через очередь код не идёт — её аргументы лежат в БД"


async def test_an_unlinked_primary_contact_gets_the_code_on_the_client_telegram(
    harness: Harness,
) -> None:
    body, _, _ = await code_body(harness, contact="primary")
    await send_code(harness, body)
    assert [chat for chat, _ in harness.bot.sent] == [TG_PRIMARY]


@pytest.mark.parametrize(
    ("language", "needle"),
    [("ru", "Код подтверждения"), ("uz", "tasdiqlash kodi"), ("en", "Confirmation code")],
)
async def test_the_text_is_in_the_language_of_the_lead(
    harness: Harness, language: str, needle: str
) -> None:
    body, _, _ = await code_body(harness, language=language)
    await send_code(harness, body)
    (_, text) = harness.bot.sent[0]
    assert needle in text
    assert CODE in text


async def test_a_contact_without_telegram_gets_nothing_and_the_row_says_why(
    harness: Harness,
) -> None:
    body, _, _ = await code_body(harness, contact="none")
    event_id = await send_code(harness, body)

    assert harness.bot.sent == []
    row = await harness.row(event_id)
    assert (row.status, row.error) == ("failed", "contact has no telegram")
    assert CODE not in await everything_stored(harness)


async def test_a_contact_of_another_client_is_refused(harness: Harness) -> None:
    body, _, _ = await code_body(harness)
    stranger_client, _ = await harness.seed_client(erp_company_id=COMPANY + 5, tg_user_id=9001)
    body["payload"]["crm_contact_id"] = await add_contact(
        harness, stranger_client, "Чужой", tg_user_id=9002
    )
    event_id = await send_code(harness, body)

    assert harness.bot.sent == [], "код не уходит контакту другого клиента"
    row = await harness.row(event_id)
    assert row.status == "failed"
    assert "not found" in (row.error or "")


async def test_an_event_of_another_company_is_refused(harness: Harness) -> None:
    body, _, _ = await code_body(harness)
    body["erp_company_id"] = COMPANY + 1
    event_id = await send_code(harness, body)
    assert harness.bot.sent == []
    assert (await harness.row(event_id)).error == "company mismatch"


async def test_an_expired_code_is_not_sent(harness: Harness) -> None:
    body, _, _ = await code_body(harness, minutes=-1)
    event_id = await send_code(harness, body)
    assert harness.bot.sent == []
    row = await harness.row(event_id)
    assert (row.status, row.error) == ("skipped", "code already expired")


async def test_without_a_running_bot_the_failure_is_recorded_without_the_code(
    harness: Harness,
) -> None:
    harness.bot_available = False
    body, _, _ = await code_body(harness)
    event_id = await send_code(harness, body)

    row = await harness.row(event_id)
    assert (row.status, row.error, row.notified_at) == ("failed", "bot is not running", None)
    assert CODE not in await everything_stored(harness)


async def test_a_telegram_failure_is_recorded_without_leaking_the_code(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def refuse(*_: Any, **__: Any) -> None:
        raise TelegramNetworkError(
            method=SendMessage(chat_id=1, text=f"code {CODE}"), message=f"text code {CODE}"
        )

    monkeypatch.setattr(harness.bot, "send_message", refuse)
    body, _, _ = await code_body(harness)
    caplog.set_level(logging.DEBUG)

    with capture_logs() as structured:
        event_id = await send_code(harness, body)

    row = await harness.row(event_id)
    assert (row.status, row.error) == ("failed", "telegram: TelegramNetworkError")
    assert CODE not in await everything_stored(harness)
    assert CODE not in caplog.text
    assert CODE not in json.dumps(structured, default=str)


# ── Повторы ─────────────────────────────────────────────────────────────────────────────────────


async def test_the_same_event_id_is_a_duplicate_and_does_not_send_a_second_code(
    harness: Harness,
) -> None:
    body, _, _ = await code_body(harness)
    event_id = await send_code(harness, body)
    raw = json.dumps(body).encode()

    again = await deliver(harness, event_id, CODE_EVENT, raw)

    assert again == (True, "duplicate")
    assert len(harness.bot.sent) == 1


async def test_a_replayed_body_under_a_new_event_id_sends_nothing(harness: Harness) -> None:
    body, _, _ = await code_body(harness)
    await send_code(harness, body)
    replay_id = await send_code(harness, body)  # тот же код под новым X-Event-Id

    assert len(harness.bot.sent) == 1
    row = await harness.row(replay_id)
    assert row.status == "rejected"
    assert "replayed body" in (row.error or "")
    assert row.notified_at is None
    assert CODE not in await everything_stored(harness)


async def test_the_journal_hash_does_not_let_the_code_be_guessed(harness: Harness) -> None:
    """Хеш в журнале — по телу без кода: перебор 4–12 цифр по нему невозможен."""
    body, _, _ = await code_body(harness)
    event_id = await send_code(harness, body)
    stored = (await harness.row(event_id)).body_sha256
    raw = json.dumps(body).encode()

    assert stored is not None
    assert stored != hashlib.sha256(raw).hexdigest()
    for guess in ("000000", CODE, "123456"):
        guessed = {**body, "payload": {**body["payload"], "code": guess}}
        assert stored != hashlib.sha256(json.dumps(guessed).encode()).hexdigest()


async def test_the_sweeper_and_the_queue_never_touch_a_code_row(harness: Harness) -> None:
    body, _, _ = await code_body(harness)
    event_id = await send_code(harness, body)

    assert await harness.service.sweep() == 0
    assert await harness.service.process_event(event_id) is True  # уже обработано: ничего нового
    assert len(harness.bot.sent) == 1


# ── Тело, которое не разобралось, кода в журнал не уносит ───────────────────────────────────────


async def test_a_rejected_code_event_keeps_no_code_in_the_journal(harness: Harness) -> None:
    body, _, _ = await code_body(harness)
    body["payload"].pop("expires_at")  # не по схеме → rejected, но тело записывается
    event_id = await send_code(harness, body)

    row = await harness.row(event_id)
    assert row.status == "rejected"
    assert row.payload["payload"]["code"] == REDACTED
    assert harness.bot.sent == []
    assert CODE not in await everything_stored(harness)


async def test_a_code_event_with_a_wrong_header_type_keeps_no_code_either(
    harness: Harness,
) -> None:
    body, _, _ = await code_body(harness)
    raw = json.dumps(body).encode()
    event_id = str(uuid.uuid4())

    result = await deliver(harness, event_id, "quote.sent", raw)

    assert result == (False, "rejected")
    assert CODE not in await everything_stored(harness)


async def test_a_broken_json_of_a_code_event_is_not_kept_even_in_part(harness: Harness) -> None:
    raw = f'{{"event": "{CODE_EVENT}", "payload": {{"code": "{CODE}"'.encode()  # оборван
    event_id = str(uuid.uuid4())

    result = await deliver(harness, event_id, CODE_EVENT, raw)

    assert result == (False, "rejected")
    assert CODE not in await everything_stored(harness)


async def test_unknown_fields_in_a_code_event_do_not_break_it(harness: Harness) -> None:
    """Терпимый читатель (Q-FIX35-4): новое поле ERP не отказ и не дыра для кода."""
    body, _, _ = await code_body(harness)
    body["from_the_future"] = {"code": CODE}
    body["payload"]["channel_hint"] = "sms"
    event_id = await send_code(harness, body)

    assert [chat for chat, _ in harness.bot.sent] == [TG_CONTACT]
    assert (await harness.row(event_id)).status == "processed"


# ── Исходы КП: кто принял ───────────────────────────────────────────────────────────────────────


async def test_the_feed_names_the_contact_who_accepted_the_quote(harness: Harness) -> None:
    body, client_id, lead_id = await seeded(harness, "quote.accepted")
    body["payload"]["crm_contact_id"] = await add_contact(harness, client_id, "Иван Петров")
    await harness.service.process_event(await receive(harness, body))

    (note,) = await notes(harness, lead_id)
    assert "Иван Петров" in note
    assert "акцептовал" in note
    assert f"#{body['payload']['erp_quote_id']}" in note


async def test_the_feed_names_the_contact_who_rejected_the_quote_with_the_reason(
    harness: Harness,
) -> None:
    body, client_id, lead_id = await seeded(harness, "quote.rejected")
    contact_id = await add_contact(harness, client_id, "Алия Каримова")
    body["payload"].update(crm_contact_id=contact_id, reason="Дорого")
    await harness.service.process_event(await receive(harness, body))

    (note,) = await notes(harness, lead_id)
    assert "Алия Каримова" in note
    assert "отклонено" in note
    assert "Дорого" in note


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("quote.accepted", "Клиент акцептовал КП #1203 v2."),
        ("quote.rejected", "КП #1203 v2 отклонено клиентом."),
    ],
)
async def test_without_a_crm_contact_the_feed_stays_neutral(
    harness: Harness, event: str, expected: str
) -> None:
    body, _, lead_id = await seeded(harness, event)
    body["payload"].pop("crm_contact_id", None)
    body["payload"].pop("reason", None)
    body["payload"]["erp_contact_id"] = 311  # ERP контакт знает, CRM — нет
    await harness.service.process_event(await receive(harness, body))

    (note,) = await notes(harness, lead_id)
    assert note == expected


async def test_a_contact_of_another_client_is_never_named_in_the_feed(harness: Harness) -> None:
    other_client, _ = await harness.seed_client(erp_company_id=COMPANY + 7, tg_user_id=9100)
    stranger = await add_contact(harness, other_client, "Посторонний Контакт")
    body, _, lead_id = await seeded(harness, "quote.accepted")
    body["payload"]["crm_contact_id"] = stranger
    await harness.service.process_event(await receive(harness, body))

    (note,) = await notes(harness, lead_id)
    assert "Посторонний" not in note


async def test_viewing_the_quote_does_not_name_a_contact(harness: Harness) -> None:
    body, client_id, lead_id = await seeded(harness, "quote.viewed")
    body["payload"]["crm_contact_id"] = await add_contact(harness, client_id, "Иван Петров")
    await harness.service.process_event(await receive(harness, body))
    (note,) = await notes(harness, lead_id)
    assert "Иван Петров" not in note


async def test_client_row_is_not_changed_by_a_code_event(harness: Harness) -> None:
    body, client_id, _ = await code_body(harness)
    await send_code(harness, body)
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    assert client.erp_company_id == COMPANY


def test_the_example_of_the_contract_carries_a_code_that_is_not_a_real_one() -> None:
    assert example_event(CODE_EVENT)["payload"]["code"] == "000000"
