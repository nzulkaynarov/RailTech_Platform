"""Приёмник шины и проекция сотрудников (pg): подпись, идемпотентность, порядок снимков, отключение."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from tests.conftest import BUS_SECRET_CRM_EDS, BUS_SECRET_ERP_EDS, BUS_SECRET_UNRELATED
from tests.helpers import deactivated_event, example, signed, user_event

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


async def deliver(client: httpx.AsyncClient, envelope: dict[str, Any], **kw: Any) -> httpx.Response:
    headers, body = signed(envelope, **kw)
    return await client.post("/bus/v1/events", headers=headers, content=body)


async def receive_and_process(client: httpx.AsyncClient, container: Container, envelope: dict[str, Any]) -> str | None:
    response = await deliver(client, envelope)
    assert response.status_code == 200, response.text
    return await container.bus.process_inbox(envelope["id"])


async def find_employee(container: Container, crm_user_id: int = 7) -> dict[str, Any] | None:
    async with container.session_factory() as session:
        row = (
            (await session.execute(text("SELECT * FROM employees WHERE crm_user_id = :id"), {"id": crm_user_id}))
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def employee(container: Container, crm_user_id: int = 7) -> dict[str, Any]:
    row = await find_employee(container, crm_user_id)
    assert row is not None, f"сотрудника {crm_user_id} нет в проекции"
    return row


async def test_signed_event_is_received_then_projected(client: httpx.AsyncClient, container: Container) -> None:
    envelope = user_event("created", when=T0, updated_at=T0.isoformat())
    response = await deliver(client, envelope)
    assert (response.status_code, response.json()["status"]) == (200, "received")
    assert await find_employee(container) is None  # проекция — задачей очереди, не в запросе приёмника

    assert await container.bus.process_inbox(envelope["id"]) == "processed"
    row = await employee(container)
    assert (row["email"], row["full_name"], row["is_active"], row["language"]) == (
        "aliya.karimova@example.com",
        "Алия Каримова",
        True,
        "ru",
    )
    assert row["permissions_eds"] == ["letters.read", "registry.read"]
    assert str(row["last_event_id"]) == envelope["id"]


@pytest.mark.parametrize(
    "case",
    ["no_headers", "bad_signature", "other_pair_secret", "wrong_publisher"],
)
async def test_unsigned_or_wrongly_signed_event_is_rejected(
    client: httpx.AsyncClient, container: Container, case: str
) -> None:
    envelope = user_event("created", when=T0)
    if case == "no_headers":
        response = await client.post("/bus/v1/events", json=envelope)
    elif case == "bad_signature":
        response = await deliver(client, envelope, secret=BUS_SECRET_UNRELATED)
    elif case == "other_pair_secret":
        response = await deliver(client, envelope, secret=BUS_SECRET_ERP_EDS)
    else:  # ERP подписывает чужой для себя тип секретом пары CRM → EDS: источник не совпадает с издателем
        response = await deliver(client, envelope, publisher="erp", secret=BUS_SECRET_CRM_EDS)
    assert response.status_code == 401
    assert await find_employee(container) is None
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM rt_bus_inbox"))).scalar() == 0


async def test_duplicate_delivery_is_not_processed_twice(client: httpx.AsyncClient, container: Container) -> None:
    envelope = user_event("created", when=T0)
    assert (await deliver(client, envelope)).json()["status"] == "received"
    assert (await deliver(client, envelope)).json()["status"] == "duplicate"
    assert await container.bus.process_inbox(envelope["id"]) == "processed"
    assert await container.bus.process_inbox(envelope["id"]) == "processed"  # повтор задачи — без повторной обработки


async def test_older_snapshot_is_not_applied(client: httpx.AsyncClient, container: Container) -> None:
    newer = user_event("updated", when=T0 + timedelta(hours=2), full_name="Новое имя", updated_at=iso(T0, 2))
    older = user_event("updated", when=T0 + timedelta(hours=3), full_name="Старое имя", updated_at=iso(T0, 1))
    await receive_and_process(client, container, newer)
    await receive_and_process(client, container, older)  # пришёл позже, но снимок старше
    row = await employee(container)
    assert row["full_name"] == "Новое имя"
    assert str(row["last_event_id"]) == newer["id"]


async def test_same_snapshot_with_new_event_id_is_idempotent(client: httpx.AsyncClient, container: Container) -> None:
    first = user_event("created", when=T0, updated_at=iso(T0, 0))
    again = user_event("updated", when=T0, updated_at=iso(T0, 0))
    await receive_and_process(client, container, first)
    await receive_and_process(client, container, again)
    row = await employee(container)
    assert row["permissions_eds"] == ["letters.read", "registry.read"]


async def test_permissions_are_replaced_as_a_whole(client: httpx.AsyncClient, container: Container) -> None:
    await receive_and_process(client, container, user_event("created", when=T0, updated_at=iso(T0, 0)))
    revoked = user_event(
        "updated", when=T0, updated_at=iso(T0, 1), permissions={"eds": ["memos.create"]}, full_name="Алия"
    )
    await receive_and_process(client, container, revoked)
    row = await employee(container)
    assert row["permissions_eds"] == ["memos.create"]


async def test_snapshot_without_permissions_field_means_no_access(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Старый CRM (до E4) поля `permissions` не шлёт: EDS читает снимок терпимо, прав нет."""
    envelope = user_event("created", when=T0, updated_at=iso(T0, 0))
    del envelope["data"]["user"]["permissions"]
    await receive_and_process(client, container, envelope)
    row = await employee(container)
    assert row["permissions_eds"] == []


async def test_deactivation_blocks_and_newer_snapshot_reactivates(
    client: httpx.AsyncClient, container: Container
) -> None:
    await receive_and_process(client, container, user_event("created", when=T0, updated_at=iso(T0, 0)))
    await receive_and_process(client, container, deactivated_event(when=T0 + timedelta(hours=1)))
    row = await employee(container)
    assert row["is_active"] is False
    assert row["email"] == "aliya.karimova@example.com"

    stale = user_event("updated", when=T0 + timedelta(hours=2), updated_at=iso(T0, 0.5))  # старее отключения
    await receive_and_process(client, container, stale)
    row = await employee(container)
    assert row["is_active"] is False

    back = user_event("updated", when=T0 + timedelta(hours=3), updated_at=iso(T0, 2))
    await receive_and_process(client, container, back)
    row = await employee(container)
    assert row["is_active"] is True


async def test_deactivation_with_old_event_time_still_deactivates(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Часы CRM ушли назад: `deactivated` старее сохранённого снимка всё равно отключает (в безопасную сторону)."""
    await receive_and_process(client, container, user_event("created", when=T0, updated_at=iso(T0, 5)))
    await receive_and_process(client, container, deactivated_event(when=T0 + timedelta(hours=1)))
    row = await employee(container)
    assert row["is_active"] is False
    assert row["updated_at"] == T0 + timedelta(hours=5)  # версия не откатилась

    older = user_event("updated", when=T0 + timedelta(hours=6), updated_at=iso(T0, 3))
    await receive_and_process(client, container, older)  # старый снимок доступ не возвращает
    assert (await employee(container))["is_active"] is False
    newer = user_event("updated", when=T0 + timedelta(hours=7), updated_at=iso(T0, 6))
    await receive_and_process(client, container, newer)  # настоящее повторное включение
    assert (await employee(container))["is_active"] is True


async def test_deactivation_arriving_first_leaves_a_tombstone(client: httpx.AsyncClient, container: Container) -> None:
    await receive_and_process(client, container, deactivated_event(when=T0 + timedelta(hours=1)))
    tomb = await employee(container)
    assert tomb["is_active"] is False
    assert tomb["email"] == ""

    await receive_and_process(client, container, user_event("created", when=T0, updated_at=iso(T0, 0)))
    row = await employee(container)
    assert row["is_active"] is False  # запоздавший `created` доступа не возвращает


async def test_event_without_handler_is_skipped(client: httpx.AsyncClient, container: Container) -> None:
    """Тип без обработчика EDS (здесь `erp.quote.sent`) приёмник записывает как `skipped` и отвечает 200."""
    envelope = example("erp/quote.sent.v1")
    response = await deliver(client, envelope, publisher="erp", secret=BUS_SECRET_ERP_EDS)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


async def test_invalid_payload_is_rejected_with_422(client: httpx.AsyncClient) -> None:
    envelope = user_event("created", when=T0)
    envelope["data"]["user"]["is_active"] = "maybe"
    assert (await deliver(client, envelope)).status_code == 422


async def test_unknown_event_id_is_ignored_by_process_inbox(container: Container) -> None:
    assert await container.bus.process_inbox(str(uuid.uuid4())) is None


def iso(base: datetime, hours: float) -> str:
    return (base + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
