"""События ERP → CRM на настоящей БД; примеры контракта как фикстуры (FIX-35 → B4; I-15, G-5).

Код акцепта (`quote.acceptance_code_requested`) — отдельно: `test_erp_acceptance_code.py`.

Вход — примеры полного конверта из `packages/contracts/events/erp/examples` (те же файлы использует
ERP): подписанная доставка через настоящий приёмник шины → запись inbox → обработка → зеркало
сделки, лента лида, индекс документов, сообщения. Отдельно: пропуск неизвестного типа, терпимость к
новым полям, upsert документов по `erp_document_id` (повторный выпуск — одна строка, Q-FIX38-1),
повтор доставки с тем же id.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from rt_bus.envelope import parse_time
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.erp_event import CODE_TYPE, NOT_FOR_CRM
from app.models.clients import Client, Document
from app.models.leads import LeadNote
from tests.bus_events import event_types, example_envelope
from tests.integration.bus_harness import Harness

pytestmark = pytest.mark.integration

#: Код акцепта не проходит очередь и журнал как остальные: отдельный набор тестов.
ALL_TYPES = [t for t in event_types("erp") if t != CODE_TYPE and t not in NOT_FOR_CRM]
COMPANY = 118  # erp_company_id в примерах контракта
#: События, по которым бот пишет клиенту (`client_message` в erp_bot_messages); по остальным молчит.
CLIENT_MESSAGE_EVENTS = {
    "uz.railtech.erp.quote.sent.v1",
    "uz.railtech.erp.invoice.issued.v1",
    "uz.railtech.erp.invoice.paid.v1",
    "uz.railtech.erp.delivery.status_changed.v1",
    "uz.railtech.erp.delivery.eta_changed.v1",
    "uz.railtech.erp.act.issued.v1",
}


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Any:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def seeded(
    harness: Harness, event_type: str, tg_user_id: int = 777
) -> tuple[dict[str, Any], int, int]:
    """Клиент с лидом и Telegram и пример конверта, адресованный этому клиенту."""
    client_id, lead_id = await harness.seed_client(erp_company_id=COMPANY, tg_user_id=tg_user_id)
    envelope = example_envelope(event_type)
    envelope["id"] = str(uuid.uuid4())
    envelope["data"]["crm_client_id"] = client_id
    return envelope, client_id, lead_id


async def receive(harness: Harness, envelope: dict[str, Any]) -> str:
    """Подписанная доставка через настоящий приёмник; возвращает id события."""
    result = await harness.post(envelope)
    assert (result.status_code, result.body["status"]) == (200, "received"), result.body
    return str(envelope["id"])


async def notes(harness: Harness, lead_id: int) -> list[str]:
    async with harness.sessions() as session:
        rows = await session.scalars(select(LeadNote).where(LeadNote.lead_id == lead_id))
        return [row.text for row in rows]


# ── 1. Каждое событие контракта: приём → обработка → результат ───────────────────────────────────


@pytest.mark.parametrize("event_type", ALL_TYPES)
async def test_every_contract_event_is_received_and_applied(
    harness: Harness, event_type: str
) -> None:
    envelope, client_id, lead_id = await seeded(harness, event_type)

    event_id = await receive(harness, envelope)
    received = await harness.inbox(event_id)
    assert received["status"] == "received"
    assert harness.enqueued == [event_id]

    assert await harness.process(event_id) == "processed"
    row = await harness.inbox(event_id)
    assert (row["status"], row["error"]) == ("processed", None)

    assert len(await notes(harness, lead_id)) == 1, "каждое событие пишет одну запись в ленту лида"
    deals = await harness.deals()
    data = envelope["data"]
    if "deal" in data:
        assert [d.erp_deal_id for d in deals] == [data["deal"]["erp_deal_id"]]
        assert deals[0].external_stage == data["deal"]["stage"]
        assert deals[0].client_id == client_id
        assert deals[0].external_stage_at == parse_time(envelope["time"])
    else:
        assert deals == []
    assert len(harness.bot.sent) == (1 if event_type in CLIENT_MESSAGE_EVENTS else 0)


async def test_processing_a_contract_event_twice_changes_nothing(harness: Harness) -> None:
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.invoice.issued.v1")
    event_id = await receive(harness, envelope)

    assert await harness.process(event_id) == "processed"
    assert await harness.process(event_id) == "processed"

    assert len(await notes(harness, lead_id)) == 1
    assert len(harness.bot.sent) == 1
    assert len(await harness.deals()) == 1


async def test_deal_won_and_lost_close_the_local_deal(harness: Harness) -> None:
    won, _, _ = await seeded(harness, "uz.railtech.erp.deal.won.v1")
    await harness.process(await receive(harness, won))
    [deal] = await harness.deals()
    assert deal.stage == "won"
    assert str(deal.amount) == won["data"]["payload"]["amount"]
    assert deal.closed_at == parse_time(won["time"])

    lost, _, _ = await seeded(harness, "uz.railtech.erp.deal.lost.v1", tg_user_id=779)
    lost["data"]["deal"]["erp_deal_id"] = 906
    await harness.process(await receive(harness, lost))
    closed = [d for d in await harness.deals() if d.erp_deal_id == 906]
    assert [(d.stage, d.lost_reason) for d in closed] == [
        ("lost", lost["data"]["payload"]["lost_reason"])
    ]


async def test_stage_and_outcome_follow_the_payload_of_the_event(harness: Harness) -> None:
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.deal.stage_changed.v1")
    await harness.process(await receive(harness, envelope))
    payload = envelope["data"]["payload"]
    [deal] = await harness.deals()
    assert deal.external_stage == payload["to"]
    [note] = await notes(harness, lead_id)
    assert f"{payload['from']} → {payload['to']}" in note
    assert payload["reason"] in note


async def test_line_decisions_notify_the_feed_and_never_the_client(harness: Harness) -> None:
    disputed, _, lead_id = await seeded(harness, "uz.railtech.erp.delivery.line_disputed.v1")
    await harness.process(await receive(harness, disputed))
    [note] = await notes(harness, lead_id)
    assert disputed["data"]["payload"]["remark"] in note
    assert harness.bot.sent == []


# ── 2. Терпимый читатель и неизвестное событие ────────────────────────────────────────────────────


async def test_new_fields_from_a_newer_erp_are_ignored_on_the_real_path(harness: Harness) -> None:
    envelope, _, _ = await seeded(harness, "uz.railtech.erp.invoice.paid.v1")
    data = envelope["data"]
    data["from_the_future"] = True
    data["payload"]["from_the_future"] = {"a": 1}
    data["deal"]["from_the_future"] = 1
    envelope["futureattribute"] = "x"  # расширение CloudEvents (L1): читатель терпим
    event_id = await receive(harness, envelope)

    assert await harness.process(event_id) == "processed"
    assert (await harness.inbox(event_id))["status"] == "processed"


@pytest.mark.parametrize(
    "event_type", ["uz.railtech.erp.warehouse.exploded.v1", "uz.railtech.erp.quote.sent.v2"]
)
async def test_an_unknown_type_or_a_newer_version_is_skipped_with_200_and_changes_nothing(
    harness: Harness, event_type: str
) -> None:
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.quote.sent.v1")
    parts = event_type.split(".")
    envelope["type"] = event_type
    envelope["dataschema"] = f"rt://contracts/events/erp/{parts[3]}.{parts[4]}/{parts[5]}"

    result = await harness.post(envelope)

    assert (result.status_code, result.body["status"]) == (200, "skipped")
    event_id = str(envelope["id"])
    assert (await harness.inbox(event_id))["status"] == "skipped"
    assert harness.enqueued == []
    assert await harness.deals() == []
    assert await notes(harness, lead_id) == []
    assert harness.bot.sent == []


async def test_a_known_event_with_a_broken_body_is_422_and_not_stored(harness: Harness) -> None:
    envelope, _, _ = await seeded(harness, "uz.railtech.erp.invoice.issued.v1")
    del envelope["data"]["payload"]["due_date"]

    result = await harness.post(envelope)

    assert (result.status_code, result.body) == (422, {"error": "invalid_data"})
    async with harness.sessions() as session:
        from sqlalchemy import text

        count = await session.scalar(text("SELECT count(*) FROM rt_bus_inbox"))
    assert count == 0


async def test_skipped_events_do_not_light_up_the_external_services_center(
    harness: Harness,
) -> None:
    from app.repositories.external_services import erp_events_stats

    envelope, _, _ = await seeded(harness, "uz.railtech.erp.quote.sent.v1")
    envelope["type"] = "uz.railtech.erp.warehouse.exploded.v1"
    await harness.post(envelope)
    async with harness.sessions() as session:
        stats = await erp_events_stats(session, datetime.now(UTC))
    assert (stats.dead, stats.failed, stats.stuck, stats.last_error) == (0, 0, 0, None)


# ── 3. Индекс документов: upsert по erp_document_id (Q-FIX38-1) ───────────────────────────────────


async def documents(harness: Harness, client_id: int | None = None) -> list[Document]:
    async with harness.sessions() as session:
        query = select(Document).order_by(Document.id)
        if client_id is not None:
            query = query.where(Document.client_id == client_id)
        return list((await session.scalars(query)).all())


async def test_document_created_keeps_the_erp_document_id(harness: Harness) -> None:
    envelope, client_id, _ = await seeded(harness, "uz.railtech.erp.document.created.v1")
    await harness.process(await receive(harness, envelope))

    payload = envelope["data"]["payload"]
    [doc] = await documents(harness, client_id)
    assert doc.erp_document_id == payload["erp_document_id"]
    assert (doc.type, doc.number, doc.title) == ("invoice", payload["number"], payload["title"])
    assert doc.extract_status == "skipped"
    assert doc.is_visible_to_client is True


async def test_a_repeated_release_of_a_document_is_one_row(harness: Harness) -> None:
    first, client_id, lead_id = await seeded(harness, "uz.railtech.erp.document.created.v1")
    await harness.process(await receive(harness, first))

    again = example_envelope("uz.railtech.erp.document.created.v1")
    again["id"] = str(uuid.uuid4())
    again["data"]["crm_client_id"] = client_id
    again["time"] = "2026-10-18T04:00:00Z"  # другое событие — не повтор доставки, а новый выпуск
    again["data"]["payload"]["title"] = "Счёт на оплату (исправленный)"
    await harness.process(await receive(harness, again))

    [doc] = await documents(harness, client_id)
    assert doc.title == "Счёт на оплату (исправленный)"
    assert doc.erp_document_id == first["data"]["payload"]["erp_document_id"]
    created, updated = await notes(harness, lead_id)  # две записи ленты: создан и обновлён
    assert "создан" in created
    assert "обновлён" in updated


async def test_different_documents_and_different_clients_get_their_own_rows(
    harness: Harness,
) -> None:
    first, client_id, _ = await seeded(harness, "uz.railtech.erp.document.created.v1")
    await harness.process(await receive(harness, first))

    other = example_envelope("uz.railtech.erp.document.created.v1")
    other["id"] = str(uuid.uuid4())
    other["data"]["crm_client_id"] = client_id
    other["data"]["payload"]["erp_document_id"] += 8  # другой документ того же клиента
    await harness.process(await receive(harness, other))
    assert len(await documents(harness, client_id)) == 2

    second_client, _ = await harness.seed_client(erp_company_id=COMPANY + 1, tg_user_id=778)
    foreign = example_envelope("uz.railtech.erp.document.created.v1")
    foreign["id"] = str(uuid.uuid4())
    foreign["data"]["crm_client_id"] = second_client
    foreign["data"]["erp_company_id"] = COMPANY + 1
    foreign["data"]["deal"]["erp_deal_id"] = 977
    await harness.process(await receive(harness, foreign))
    assert len(await documents(harness, second_client)) == 1
    assert len(await documents(harness)) == 3


async def test_the_database_forbids_two_rows_for_one_erp_document(harness: Harness) -> None:
    envelope, client_id, _ = await seeded(harness, "uz.railtech.erp.document.created.v1")
    await harness.process(await receive(harness, envelope))

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
        await insert(envelope["data"]["payload"]["erp_document_id"])
    await insert(None)  # загруженные менеджером документы идентификатора не имеют — их много
    await insert(None)


# ── 4. Повтор доставки ────────────────────────────────────────────────────────────────────────────


async def test_a_repeated_delivery_of_the_same_event_is_a_duplicate_and_applied_once(
    harness: Harness,
) -> None:
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.invoice.issued.v1")
    event_id = await receive(harness, envelope)
    await harness.process(event_id)

    again = await harness.post(envelope)

    assert (again.status_code, again.body["status"]) == (200, "duplicate")
    assert harness.enqueued == [event_id], "повтор в очередь не ставится"
    assert len(await notes(harness, lead_id)) == 1
    assert len(harness.bot.sent) == 1


async def test_two_events_with_different_ids_are_both_applied(harness: Harness) -> None:
    envelope, _, lead_id = await seeded(harness, "uz.railtech.erp.quote.viewed.v1")
    other = {**envelope, "id": str(uuid.uuid4()), "time": "2026-10-13T06:41:00Z"}
    for item in (envelope, other):
        await harness.process(await receive(harness, item))
    assert len(await notes(harness, lead_id)) == 2


async def test_a_company_the_client_does_not_have_changes_nothing_in_the_client(
    harness: Harness,
) -> None:
    envelope, client_id, _ = await seeded(harness, "uz.railtech.erp.contract.signed.v1")
    envelope["data"]["erp_company_id"] = COMPANY + 5
    event_id = await receive(harness, envelope)

    assert await harness.process(event_id) == "received", "ошибка обработки — автоповтор"

    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    assert client.erp_company_id == COMPANY
    assert await harness.deals() == []
