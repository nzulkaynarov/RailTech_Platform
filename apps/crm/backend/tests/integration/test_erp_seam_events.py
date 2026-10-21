"""События ERP → CRM на настоящей БД; примеры контракта как фикстуры (FIX-35; I-15, G-5).

Код акцепта (`quote.acceptance_code_requested`) — отдельно: `test_erp_acceptance_code.py`.

Вход — тела из `packages/contracts/examples/events` (те же файлы использует ERP): подписанный
вебхук через настоящий приёмник → строка журнала → обработка → зеркало сделки, лента лида,
индекс документов, сообщения. Отдельно: пропуск неизвестного события, терпимость к новым полям,
upsert документов по `erp_document_id` (повторный выпуск — одна строка, Q-FIX38-1), отказ от
повтора тела под другим `X-Event-Id`.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import AuthError
from app.models.clients import Client, Document
from app.models.deals import Deal
from app.models.integrations import ErpIncomingEvent
from app.models.leads import LeadNote
from app.schemas.erp_events import CODE_EVENT
from app.services.erp_events import sign_v2
from tests.integration.test_erp_events import Harness
from tests.seam_events import event_types, example_event

pytestmark = pytest.mark.integration

SECRET = "x" * 40  # секрет Harness (Settings.erp_webhook_secret)
#: Код акцепта не проходит очередь и журнал как остальные: отдельный набор тестов.
ALL_EVENTS = [event for event in event_types() if event != CODE_EVENT]
COMPANY = 118  # erp_company_id в примерах контракта
#: События, по которым бот пишет клиенту (`client_message` в erp_bot_messages); по остальным молчит.
CLIENT_MESSAGE_EVENTS = {
    "quote.sent",
    "invoice.issued",
    "invoice.paid",
    "delivery.status_changed",
    "delivery.eta_changed",
    "act.issued",
}


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Harness:
    return Harness(sessions)


def sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def receive(harness: Harness, body: dict[str, Any], event_id: str | None = None) -> str:
    """Подписанный вебхук через настоящий приёмник; возвращает id события."""
    event_id = event_id or str(uuid.uuid4())
    raw = json.dumps(body).encode()
    result = await harness.service.receive_event(event_id, body["event"], sign(raw), raw)
    assert result == (False, "enqueued")
    return event_id


async def seeded(
    harness: Harness, event: str, tg_user_id: int = 777
) -> tuple[dict[str, Any], int, int]:
    """Клиент с лидом и Telegram и тело примера, адресованное этому клиенту."""
    client_id, lead_id = await harness.seed_client(erp_company_id=COMPANY, tg_user_id=tg_user_id)
    body = example_event(event)
    body["crm_client_id"] = client_id
    return body, client_id, lead_id


async def notes(harness: Harness, lead_id: int) -> list[str]:
    async with harness.sessions() as session:
        rows = await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))
        return [row.text for row in rows]


# ── 1. Каждое событие контракта: приём → обработка → результат ───────────────────────────────────


@pytest.mark.parametrize("event", ALL_EVENTS)
async def test_every_contract_event_is_received_and_applied(harness: Harness, event: str) -> None:
    body, client_id, lead_id = await seeded(harness, event)

    event_id = await receive(harness, body)
    received = await harness.row(event_id)
    assert (received.status, received.event_type) == ("received", event)
    assert received.payload == body, "журнал хранит тело как пришло — ничего не теряется"
    assert harness.enqueued == [event_id]

    assert await harness.service.process_event(event_id) is True
    row = await harness.row(event_id)
    assert (row.status, row.error, row.erp_company_id, row.crm_client_id) == (
        "processed",
        None,
        COMPANY,
        client_id,
    )

    assert len(await notes(harness, lead_id)) == 1, "каждое событие пишет одну запись в ленту лида"
    deals = await harness.deals()
    if "deal" in body:
        assert [d.erp_deal_id for d in deals] == [body["deal"]["erp_deal_id"]]
        assert deals[0].external_stage == body["deal"]["stage"]
        assert deals[0].client_id == client_id
        assert deals[0].external_stage_at == datetime.fromisoformat(body["occurred_at"])
    else:
        assert deals == []
    assert len(harness.bot.sent) == (1 if event in CLIENT_MESSAGE_EVENTS else 0)


async def test_processing_a_contract_event_twice_changes_nothing(harness: Harness) -> None:
    body, _, lead_id = await seeded(harness, "invoice.issued")
    event_id = await receive(harness, body)

    assert await harness.service.process_event(event_id) is True
    assert await harness.service.process_event(event_id) is True

    assert len(await notes(harness, lead_id)) == 1
    assert len(harness.bot.sent) == 1
    assert len(await harness.deals()) == 1


async def test_deal_won_and_lost_close_the_local_deal(harness: Harness) -> None:
    won, _, _ = await seeded(harness, "deal.won")
    await harness.service.process_event(await receive(harness, won))
    [deal] = await harness.deals()
    assert deal.stage == "won"
    assert str(deal.amount) == won["payload"]["amount"]
    assert deal.closed_at == datetime.fromisoformat(won["occurred_at"])

    lost, _, _ = await seeded(harness, "deal.lost", tg_user_id=779)
    lost["deal"]["erp_deal_id"] = 906
    await harness.service.process_event(await receive(harness, lost))
    closed = [d for d in await harness.deals() if d.erp_deal_id == 906]
    assert [(d.stage, d.lost_reason) for d in closed] == [("lost", lost["payload"]["lost_reason"])]


async def test_stage_and_outcome_follow_the_payload_of_the_event(harness: Harness) -> None:
    body, _, lead_id = await seeded(harness, "deal.stage_changed")
    await harness.service.process_event(await receive(harness, body))
    [deal] = await harness.deals()
    assert deal.external_stage == body["payload"]["to"]
    [note] = await notes(harness, lead_id)
    assert f"{body['payload']['from']} → {body['payload']['to']}" in note
    assert body["payload"]["reason"] in note


async def test_line_decisions_notify_the_feed_and_never_the_client(harness: Harness) -> None:
    disputed, _, lead_id = await seeded(harness, "delivery.line_disputed")
    await harness.service.process_event(await receive(harness, disputed))
    [note] = await notes(harness, lead_id)
    assert disputed["payload"]["remark"] in note
    assert harness.bot.sent == []


# ── 2. Терпимый читатель и неизвестное событие ────────────────────────────────────────────────────


async def test_new_fields_from_a_newer_erp_are_ignored_on_the_real_path(harness: Harness) -> None:
    body, _, _ = await seeded(harness, "invoice.paid")
    body["from_the_future"] = True
    body["payload"]["from_the_future"] = {"a": 1}
    body["deal"]["from_the_future"] = 1
    event_id = await receive(harness, body)

    assert await harness.service.process_event(event_id) is True
    assert (await harness.row(event_id)).status == "processed"


async def test_an_unknown_event_is_skipped_with_200_and_changes_nothing(harness: Harness) -> None:
    body, client_id, lead_id = await seeded(harness, "quote.sent")
    body["event"] = "warehouse.exploded"
    raw = json.dumps(body).encode()
    event_id = str(uuid.uuid4())

    result = await harness.service.receive_event(event_id, "warehouse.exploded", sign(raw), raw)

    assert result == (False, "skipped")
    row = await harness.row(event_id)
    assert (row.status, row.error) == ("skipped", "unknown event type: warehouse.exploded")
    assert (row.erp_company_id, row.crm_client_id) == (COMPANY, client_id)
    assert row.processed_at is not None
    assert harness.enqueued == []
    assert await harness.deals() == []
    assert await notes(harness, lead_id) == []
    assert await harness.service.process_event(event_id) is False


async def test_a_known_event_with_a_broken_body_is_rejected_not_skipped(harness: Harness) -> None:
    body, _, _ = await seeded(harness, "invoice.issued")
    del body["payload"]["due_date"]
    raw = json.dumps(body).encode()
    event_id = str(uuid.uuid4())

    assert await harness.service.receive_event(event_id, body["event"], sign(raw), raw) == (
        False,
        "rejected",
    )
    row = await harness.row(event_id)
    assert row.status == "rejected"
    assert "payload.due_date" in (row.error or "")


async def test_skipped_events_do_not_light_up_the_external_services_center(
    harness: Harness,
) -> None:
    from datetime import UTC

    from app.repositories.external_services import erp_events_stats

    body, _, _ = await seeded(harness, "quote.sent")
    body["event"] = "warehouse.exploded"
    raw = json.dumps(body).encode()
    await harness.service.receive_event(str(uuid.uuid4()), "warehouse.exploded", sign(raw), raw)
    async with harness.sessions() as session:
        stats = await erp_events_stats(session, datetime.now(UTC))
    assert (stats.rejected, stats.failed, stats.stuck, stats.last_error) == (0, 0, 0, None)


# ── 3. Индекс документов: upsert по erp_document_id (Q-FIX38-1) ───────────────────────────────────


async def documents(harness: Harness, client_id: int | None = None) -> list[Document]:
    async with harness.sessions() as session:
        query = select(Document).order_by(Document.id)
        if client_id is not None:
            query = query.where(Document.client_id == client_id)
        return list((await session.scalars(query)).all())


async def test_document_created_keeps_the_erp_document_id(harness: Harness) -> None:
    body, client_id, _ = await seeded(harness, "document.created")
    await harness.service.process_event(await receive(harness, body))

    [doc] = await documents(harness, client_id)
    assert doc.erp_document_id == body["payload"]["erp_document_id"]
    assert (doc.type, doc.number, doc.title) == (
        "invoice",
        body["payload"]["number"],
        body["payload"]["title"],
    )
    assert doc.extract_status == "skipped"
    assert doc.is_visible_to_client is True


async def test_a_repeated_release_of_a_document_is_one_row(harness: Harness) -> None:
    first, client_id, lead_id = await seeded(harness, "document.created")
    await harness.service.process_event(await receive(harness, first))

    again = example_event("document.created")
    again["crm_client_id"] = client_id
    again["occurred_at"] = (
        "2026-10-18T09:00:00+05:00"  # другое тело — это не повтор, а новый выпуск
    )
    again["payload"]["title"] = "Счёт на оплату (исправленный)"
    event_id = await receive(harness, again)
    await harness.service.process_event(event_id)

    [doc] = await documents(harness, client_id)
    assert doc.title == "Счёт на оплату (исправленный)"
    assert doc.erp_document_id == first["payload"]["erp_document_id"]
    created, updated = await notes(harness, lead_id)  # две записи ленты: создан и обновлён
    assert "создан" in created
    assert "обновлён" in updated


async def test_different_documents_and_different_clients_get_their_own_rows(
    harness: Harness,
) -> None:
    first, client_id, _ = await seeded(harness, "document.created")
    await harness.service.process_event(await receive(harness, first))

    other = example_event("document.created")
    other["crm_client_id"] = client_id
    other["payload"]["erp_document_id"] += 8  # другой документ того же клиента
    await harness.service.process_event(await receive(harness, other))
    assert len(await documents(harness, client_id)) == 2

    second_client, _ = await harness.seed_client(erp_company_id=COMPANY + 1, tg_user_id=778)
    foreign = example_event("document.created")
    foreign["crm_client_id"] = second_client
    foreign["erp_company_id"] = COMPANY + 1
    foreign["deal"]["erp_deal_id"] = 977
    await harness.service.process_event(await receive(harness, foreign))
    assert len(await documents(harness, second_client)) == 1
    assert len(await documents(harness)) == 3


async def test_the_database_forbids_two_rows_for_one_erp_document(harness: Harness) -> None:
    body, client_id, _ = await seeded(harness, "document.created")
    await harness.service.process_event(await receive(harness, body))

    async def insert(erp_document_id: int | None) -> None:
        async with harness.sessions() as session, session.begin():
            session.add(
                Document(
                    client_id=client_id,
                    type="other",
                    title="Дубль",
                    filename="d.pdf",
                    mime="application/pdf",
                    size_bytes=0,
                    erp_document_id=erp_document_id,
                )
            )

    with pytest.raises(IntegrityError):
        await insert(body["payload"]["erp_document_id"])
    await insert(None)  # загруженные менеджером документы идентификатора не имеют — их много
    await insert(None)


# ── 4. Повтор тела под другим X-Event-Id ──────────────────────────────────────────────────────────


async def test_a_replayed_body_under_a_new_event_id_is_rejected_and_not_applied(
    harness: Harness,
) -> None:
    body, _, lead_id = await seeded(harness, "invoice.issued")
    raw = json.dumps(body).encode()
    first, replay = str(uuid.uuid4()), str(uuid.uuid4())

    assert await harness.service.receive_event(first, body["event"], sign(raw), raw) == (
        False,
        "enqueued",
    )
    await harness.service.process_event(first)
    assert await harness.service.receive_event(replay, body["event"], sign(raw), raw) == (
        False,
        "rejected",
    )

    row = await harness.row(replay)
    assert (row.status, row.error) == (
        "rejected",
        f"replayed body: already received as event {first}",
    )
    assert row.processed_at is not None
    assert harness.enqueued == [first]
    assert await harness.service.process_event(replay) is False
    assert len(await notes(harness, lead_id)) == 1
    assert len(harness.bot.sent) == 1
    # тот же id — обычный дубль
    assert await harness.service.receive_event(first, body["event"], sign(raw), raw) == (
        True,
        "duplicate",
    )


async def test_two_events_with_different_bodies_are_both_applied(harness: Harness) -> None:
    body, _, lead_id = await seeded(harness, "quote.viewed")
    other = {**body, "occurred_at": "2026-10-13T11:41:00+05:00"}
    for item in (body, other):
        await harness.service.process_event(await receive(harness, item))
    assert len(await notes(harness, lead_id)) == 2


async def test_the_body_hash_is_stored_for_every_row(harness: Harness) -> None:
    body, _, _ = await seeded(harness, "quote.viewed")
    event_id = await receive(harness, body)
    row = await harness.row(event_id)
    assert row.body_sha256 == hashlib.sha256(json.dumps(body).encode()).hexdigest()


async def test_client_is_untouched_by_the_replayed_event(harness: Harness) -> None:
    body, client_id, _ = await seeded(harness, "contract.signed")
    raw = json.dumps(body).encode()
    await harness.service.receive_event(str(uuid.uuid4()), body["event"], sign(raw), raw)
    await harness.service.receive_event(str(uuid.uuid4()), body["event"], sign(raw), raw)
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        statuses = (await session.scalars(select(ErpIncomingEvent.status))).all()
        deals = (await session.scalars(select(Deal))).all()
    assert client is not None
    assert client.erp_company_id == COMPANY
    assert sorted(statuses) == ["received", "rejected"]
    assert deals == []  # до обработки зеркала ещё нет: повтор его не создаёт


# ── 5. Подпись v2 и окно X-Timestamp на настоящей БД (FIX-61) ─────────────────────────────────


def _stamp(offset_s: float = 0.0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _legacy_off(harness: Harness) -> None:
    harness.service._config = harness.service._config.model_copy(
        update={"erp_webhook_sign_legacy": False}
    )


async def test_v2_event_is_applied_and_the_forged_id_and_old_stamp_are_refused(
    harness: Harness,
) -> None:
    _legacy_off(harness)
    body, _, lead_id = await seeded(harness, "invoice.issued")
    raw = json.dumps(body).encode()
    event_id, stamp = str(uuid.uuid4()), _stamp()
    signature = sign_v2(SECRET, event_id, stamp, raw)

    assert await harness.service.receive_event(
        event_id, body["event"], signature, raw, timestamp=stamp
    ) == (False, "enqueued")
    await harness.service.process_event(event_id)
    assert len(await notes(harness, lead_id)) == 1

    # то же тело и та же подпись под новым X-Event-Id — отказ: подпись не сходится, строки нет
    forged = str(uuid.uuid4())
    with pytest.raises(AuthError):
        await harness.service.receive_event(forged, body["event"], signature, raw, timestamp=stamp)
    async with harness.sessions() as session:
        assert await session.get(ErpIncomingEvent, forged) is None
    # старая схема после выключения настройки — отказ
    with pytest.raises(AuthError):
        await harness.service.receive_event(forged, body["event"], sign(raw), raw, timestamp=stamp)
    # подписанное верно, но с меткой давности — `rejected`, без обработки и без хеша тела
    old_id, old = str(uuid.uuid4()), _stamp(-1200)
    assert await harness.service.receive_event(
        old_id, body["event"], sign_v2(SECRET, old_id, old, raw), raw, timestamp=old
    ) == (False, "rejected")
    row = await harness.row(old_id)
    assert (row.status, row.body_sha256) == ("rejected", None)
    assert (row.error or "").startswith("stale timestamp")
    assert len(await notes(harness, lead_id)) == 1


async def test_a_retry_with_a_fresh_stamp_replaces_the_row_rejected_for_its_stamp(
    harness: Harness,
) -> None:
    _legacy_off(harness)
    body, _, lead_id = await seeded(harness, "invoice.issued")
    raw = json.dumps(body).encode()
    event_id, stale, fresh = str(uuid.uuid4()), _stamp(-1200), _stamp()

    assert (
        await harness.service.receive_event(
            event_id, body["event"], sign_v2(SECRET, event_id, stale, raw), raw, timestamp=stale
        )
    )[1] == "rejected"
    assert await harness.service.receive_event(
        event_id, body["event"], sign_v2(SECRET, event_id, fresh, raw), raw, timestamp=fresh
    ) == (False, "enqueued")
    row = await harness.row(event_id)
    assert (row.status, row.error) == ("received", None)
    await harness.service.process_event(event_id)
    assert len(await notes(harness, lead_id)) == 1
    # принятое событие теперь — обычный дубль
    assert (
        await harness.service.receive_event(
            event_id, body["event"], sign_v2(SECRET, event_id, fresh, raw), raw, timestamp=fresh
        )
    ) == (True, "duplicate")


async def test_the_body_hash_rail_still_holds_for_v2(harness: Harness) -> None:
    """Второй рубеж (FIX-35) остаётся: то же тело под другим id с СВОЕЙ подписью v2 — повтор."""
    body, _, _ = await seeded(harness, "invoice.issued")
    raw = json.dumps(body).encode()
    first, second, stamp = str(uuid.uuid4()), str(uuid.uuid4()), _stamp()
    assert (
        await harness.service.receive_event(
            first, body["event"], sign_v2(SECRET, first, stamp, raw), raw, timestamp=stamp
        )
    )[1] == "enqueued"
    assert (
        await harness.service.receive_event(
            second, body["event"], sign_v2(SECRET, second, stamp, raw), raw, timestamp=stamp
        )
    )[1] == "rejected"
    row = await harness.row(second)
    assert (row.error or "").startswith("replayed body")
