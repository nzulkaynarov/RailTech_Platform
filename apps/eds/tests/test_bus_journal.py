"""«Журнал интеграций» шины EDS (`/api/v1/bus/*`, W13-A2, pg): сводка, доставки и DLQ, inbox с ошибками, повторы
(идемпотентно, с записью в журнал EDS) и право `bus.manage` (раздел `admin` каталога; у директора его нет)."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from app.container import Container
from app.models import JournalEntry
from tests.domain import Person, validate
from tests.helpers import example

pytestmark = pytest.mark.pg

EVENT = uuid.UUID("2f1d0c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b")
LETTER_RESOLVED = "uz.railtech.eds.letter.resolved.v1"


@pytest.fixture
async def journal_rows(container: Container) -> uuid.UUID:
    """Событие EDS, доставка которого в ERP ушла в DLQ (404), и событие ERP с упавшей обработкой (failed)."""
    incoming = example("erp/request.created.v1")
    async with container.session_factory() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO rt_bus_outbox (id, type, source, subject, correlation_id, envelope, created_at,"
                " dispatched_at) VALUES (:id, :type, 'rt://eds', 'letter/ВХ-104/26', 'req-eds-1', CAST(:env AS jsonb),"
                " now(), now())"
            ),
            {"id": EVENT, "type": LETTER_RESOLVED, "env": json.dumps({"data": {"resolution": "Рассчитать"}})},
        )
        await session.execute(
            text(
                "INSERT INTO rt_bus_delivery (event_id, event_type, subscriber, status, attempts, created_at,"
                " updated_at, last_status_code, last_error)"
                " VALUES (:id, :type, 'erp', 'dead', 1, now(), now(), 404, 'HTTP 404: nope')"
            ),
            {"id": EVENT, "type": LETTER_RESOLVED},
        )
        await session.execute(
            text(
                "INSERT INTO rt_bus_inbox (event_id, type, source, publisher, subject, correlation_id, envelope,"
                " status, attempts, error, received_at, updated_at)"
                " VALUES (:id, :type, 'rt://erp', 'erp', :subject, :corr, CAST(:env AS jsonb),"
                " 'failed', 4, 'ValueError: request is not known', now(), now())"
            ),
            {
                "id": uuid.UUID(incoming["id"]),
                "type": incoming["type"],
                "subject": incoming.get("subject"),
                "corr": incoming["correlationid"],
                "env": json.dumps(incoming),
            },
        )
    return uuid.UUID(incoming["id"])


async def test_admin_reads_overview_dlq_and_failed_inbox_without_event_bodies(
    client: httpx.AsyncClient, staff: dict[str, Person], journal_rows: uuid.UUID
) -> None:
    headers = staff["admin"].headers
    overview = await client.get("/api/v1/bus/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    validate("BusOverview", overview.json())
    body = overview.json()
    assert (body["service"], body["dlq_size"], body["inbox_failed"]) == ("eds", 1, 1)
    subs = {s["name"]: s for s in body["subscribers"]}
    # EDS доставляет eds.* ERP и BFF, запрос письма (eds.mail.requested, W18A-P1) — CRM; себе — нет
    assert set(subs) == {"crm", "erp", "platform-bff"}
    assert subs["erp"]["dead"] == 1

    dead = await client.get("/api/v1/bus/deliveries", params={"status": "dead"}, headers=headers)
    validate("BusDeliveryPage", dead.json())
    [row] = dead.json()["items"]
    assert (row["event_id"], row["subscriber"], row["last_status_code"]) == (str(EVENT), "erp", 404)
    assert "Рассчитать" not in dead.text

    inbox = await client.get("/api/v1/bus/inbox", params={"errors": "true"}, headers=headers)
    validate("BusInboxPage", inbox.json())
    [entry] = inbox.json()["items"]
    assert (entry["event_id"], entry["status"]) == (str(journal_rows), "failed")


async def test_retries_are_idempotent_and_journaled(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], journal_rows: uuid.UUID
) -> None:
    admin = staff["admin"]
    first = await client.post("/api/v1/bus/deliveries/retry-dead", json={"subscriber": "erp"}, headers=admin.headers)
    assert first.json() == {"retried": 1}
    second = await client.post("/api/v1/bus/deliveries/retry-dead", json={"subscriber": "erp"}, headers=admin.headers)
    assert second.json() == {"retried": 0}
    assert (await client.post("/api/v1/bus/deliveries/999999/retry", headers=admin.headers)).json() == {"retried": 0}
    retried = await client.post(f"/api/v1/bus/inbox/{journal_rows}/retry", headers=admin.headers)
    validate("BusRetryResult", retried.json())
    assert retried.json() == {"retried": 1}

    async with container.session_factory() as session:
        rows = (
            await session.scalars(
                select(JournalEntry).where(JournalEntry.action.like("bus.%")).order_by(JournalEntry.id)
            )
        ).all()
    assert [(r.action, r.by_crm_user_id) for r in rows] == [
        ("bus.dead_retried", admin.id),
        ("bus.dead_retried", admin.id),
        ("bus.delivery_retried", admin.id),
        ("bus.inbox_retried", admin.id),
    ]
    assert rows[0].comment == "подписчик erp, поставлено: 1"
    # без очереди (тесты) повтор обрабатывает запись сразу: обработчик ERP создал входящее письмо
    assert (await client.get("/api/v1/bus/inbox", params={"errors": "true"}, headers=admin.headers)).json() == {
        "items": [],
        "has_more": False,
    }


async def test_director_and_others_without_bus_manage_get_403(
    client: httpx.AsyncClient, staff: dict[str, Person], journal_rows: uuid.UUID
) -> None:
    for who in ("director", "manager", "nobody"):
        headers = staff[who].headers
        for method, path in (
            ("GET", "/api/v1/bus/overview"),
            ("GET", "/api/v1/bus/deliveries"),
            ("GET", "/api/v1/bus/inbox"),
            ("POST", "/api/v1/bus/deliveries/retry-dead"),
            ("POST", f"/api/v1/bus/inbox/{journal_rows}/retry"),
        ):
            response = await client.request(method, path, json={"subscriber": "erp"}, headers=headers)
            assert response.status_code == 403, (who, path, response.status_code)
            assert response.json()["details"]["permission"] == "bus.manage"


async def test_filters_are_validated(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = staff["admin"].headers
    for params in ({"status": "lost"}, {"limit": 500}, {"subscriber": "ERP!"}):
        response = await client.get("/api/v1/bus/deliveries", params=params, headers=headers)
        assert response.status_code == 422, params
        assert response.json()["code"] == "VALIDATION_FAILED"
