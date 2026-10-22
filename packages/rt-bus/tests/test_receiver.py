"""Приёмник (без БД, `MemoryReceiver`): подпись и окно, ответы L3, skipped, терпимая проверка data, дедупликация."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from rt_bus import Event, HandlerRegistry
from rt_bus.memory import MemoryReceiver

from .conftest import Clock, example, make_config, signed


@pytest.fixture
def seen() -> list[Event]:
    return []


@pytest.fixture
def receiver(clock: Clock, subscriptions_file: Path, seen: list[Event]) -> MemoryReceiver:
    registry = HandlerRegistry()

    @registry.subscribe("uz.railtech.erp.quote.*.v1")
    async def on_quote(event: Event) -> None:
        seen.append(event)

    return MemoryReceiver(make_config("crm", clock, subscriptions_file), registry=registry)


def quote_sent(**changes: Any) -> dict[str, Any]:
    envelope = example("erp/quote.sent.v1")
    envelope["id"] = str(uuid.uuid4())
    envelope.update(changes)
    return envelope


async def test_accepts_and_dedupes(receiver: MemoryReceiver, seen: list[Event]) -> None:
    headers, body = signed(quote_sent())
    first = await receiver.receive(headers, body)
    assert first.status_code == 200
    assert first.body["status"] == "processed"
    second = await receiver.receive(headers, body)
    assert (second.status_code, second.body["status"]) == (200, "duplicate")
    assert len(seen) == 1
    assert seen[0].data["deal"]["erp_deal_id"] == 905


async def test_previous_secret_accepted_during_rotation(receiver: MemoryReceiver) -> None:
    headers, body = signed(quote_sent(), secret="test-secret-erp-crm-old")
    assert (await receiver.receive(headers, body)).status_code == 200


@pytest.mark.parametrize(
    "tamper",
    [
        lambda h: h.update({"X-RT-Signature": "sha256=" + "0" * 64}),
        lambda h: h.pop("X-RT-Signature"),
        lambda h: h.update({"X-RT-Event-Id": str(uuid.uuid4())}),
        lambda h: h.pop("X-RT-Publisher"),
        # чужой издатель: секрета пары audit→crm нет
        lambda h: h.update({"X-RT-Publisher": "audit"}),
    ],
)
async def test_unauthorized(receiver: MemoryReceiver, tamper, seen: list[Event]) -> None:  # type: ignore[no-untyped-def]
    headers, body = signed(quote_sent())
    tamper(headers)
    result = await receiver.receive(headers, body)
    assert result.status_code == 401
    assert result.body == {"error": "unauthorized"}
    assert seen == []


async def test_wrong_secret_and_foreign_source(receiver: MemoryReceiver) -> None:
    headers, body = signed(quote_sent(), secret="test-secret-erp-audit")
    assert (await receiver.receive(headers, body)).status_code == 401
    # подпись верна для пары erp→crm, но source — чужой сервис
    headers, body = signed(quote_sent(source="rt://eds"))
    assert (await receiver.receive(headers, body)).status_code == 401


async def test_outside_window(receiver: MemoryReceiver, clock: Clock) -> None:
    headers, body = signed(quote_sent())
    clock.advance(301)
    assert (await receiver.receive(headers, body)).status_code == 401
    clock.advance(-2)
    assert (await receiver.receive(headers, body)).status_code == 200


async def test_bad_json_and_not_envelope(receiver: MemoryReceiver) -> None:
    headers, _ = signed(quote_sent())
    from rt_bus.signing import sign

    body = b"{not json"
    headers["X-RT-Signature"] = sign(
        "test-secret-erp-crm-new", headers["X-RT-Event-Id"], headers["X-RT-Timestamp"], body
    )
    assert (await receiver.receive(headers, body)).status_code == 400
    envelope = quote_sent()
    del envelope["specversion"]
    headers, body = signed(envelope)
    result = await receiver.receive(headers, body)
    assert (result.status_code, result.body["error"]) == (400, "invalid_envelope")


async def test_invalid_data_of_known_type_is_422(receiver: MemoryReceiver, seen: list[Event]) -> None:
    envelope = quote_sent()
    envelope["data"]["erp_company_id"] = "not-int"
    headers, body = signed(envelope)
    result = await receiver.receive(headers, body)
    assert (result.status_code, result.body["error"]) == (422, "invalid_data")
    assert seen == []


async def test_tolerant_to_new_optional_fields(receiver: MemoryReceiver, seen: list[Event]) -> None:
    envelope = quote_sent(newext="x")
    envelope["data"]["future_field"] = {"any": 1}
    envelope["data"]["payload"]["future_nested"] = True
    headers, body = signed(envelope)
    assert (await receiver.receive(headers, body)).status_code == 200
    assert seen[0].data["future_field"] == {"any": 1}


async def test_unknown_type_and_higher_version_are_skipped(receiver: MemoryReceiver, seen: list[Event]) -> None:
    deal_won = example("erp/deal.won.v1")  # обработчика нет
    headers, body = signed(deal_won)
    result = await receiver.receive(headers, body)
    assert (result.status_code, result.body["status"]) == (200, "skipped")
    v2 = quote_sent(type="uz.railtech.erp.quote.sent.v2", dataschema="rt://contracts/events/erp/quote.sent/v2")
    headers, body = signed(v2)
    result = await receiver.receive(headers, body)
    assert (result.status_code, result.body["status"]) == (200, "skipped")
    assert seen == []


async def test_handler_without_schema_is_skipped(clock: Clock, subscriptions_file: Path) -> None:
    registry = HandlerRegistry()
    calls: list[Event] = []

    @registry.subscribe("uz.railtech.erp.*.v1")
    async def any_erp(event: Event) -> None:
        calls.append(event)

    receiver = MemoryReceiver(make_config("crm", clock, subscriptions_file), registry=registry)
    envelope = quote_sent(type="uz.railtech.erp.brand_new.created.v1")
    envelope["dataschema"] = "rt://contracts/events/erp/brand_new.created/v1"
    headers, body = signed(envelope)
    result = await receiver.receive(headers, body)
    assert result.body["status"] == "skipped"
    assert calls == []


async def test_handler_error_is_503_and_retry_processes(clock: Clock, subscriptions_file: Path) -> None:
    registry = HandlerRegistry()
    attempts: list[str] = []

    @registry.subscribe("uz.railtech.erp.quote.sent.v1")
    async def flaky(event: Event) -> None:
        attempts.append(event.id)
        if len(attempts) == 1:
            raise RuntimeError("redis down")

    receiver = MemoryReceiver(make_config("crm", clock, subscriptions_file), registry=registry)
    headers, body = signed(quote_sent())
    assert (await receiver.receive(headers, body)).status_code == 503
    assert (await receiver.receive(headers, body)).status_code == 200
    assert len(attempts) == 2


def test_handler_patterns_validated() -> None:
    registry = HandlerRegistry()
    with pytest.raises(ValueError, match="pattern"):
        registry.add("quote.sent", lambda e: None)
    registry.add("uz.railtech.erp.*.v1", lambda e: None, inline=True)
    assert [h.inline for h in registry.match("uz.railtech.erp.quote.sent.v1")] == [True]
    assert registry.match("uz.railtech.erp.quote.sent.v2") == []
