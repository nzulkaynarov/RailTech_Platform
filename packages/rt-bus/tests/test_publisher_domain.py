"""Приёмник: домен типа должен принадлежать издателю пары (подпись пары), ответ 400 `foreign_type`."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from rt_bus import Event, HandlerRegistry
from rt_bus.memory import MemoryReceiver
from rt_bus.receiver import DEFAULT_PUBLISHER_DOMAINS, foreign_type

from .conftest import Clock, example, make_config, signed


@pytest.fixture
def seen() -> list[Event]:
    return []


@pytest.fixture
def erp_receiver(clock: Clock, subscriptions_file: Path, seen: list[Event]) -> MemoryReceiver:
    """Приёмник сервиса `erp`: принимает события CRM (пара crm→erp)."""
    registry = HandlerRegistry()

    @registry.subscribe("uz.railtech.crm.*.v1")
    @registry.subscribe("uz.railtech.identity.*.v1")
    @registry.subscribe("uz.railtech.erp.*.v1")
    async def on_any(event: Event) -> None:
        seen.append(event)

    return MemoryReceiver(make_config("erp", clock, subscriptions_file), registry=registry)


def envelope(rel: str, **changes: Any) -> dict[str, Any]:
    result = example(rel)
    result["id"] = str(uuid.uuid4())
    result.update(changes)
    return result


async def test_crm_may_publish_crm_and_identity(erp_receiver: MemoryReceiver, seen: list[Event]) -> None:
    for rel in ("crm/client.updated.v1", "identity/user.updated.v1"):
        headers, body = signed(envelope(rel), publisher="crm", secret="test-secret-crm-erp")
        result = await erp_receiver.receive(headers, body)
        assert (result.status_code, result.body["status"]) == (200, "processed"), rel
    assert len(seen) == 2


async def test_crm_with_erp_type_is_rejected(erp_receiver: MemoryReceiver, seen: list[Event]) -> None:
    # подпись пары верна и source — rt://crm, но тип чужого домена
    forged = envelope("erp/quote.sent.v1", source="rt://crm")
    headers, body = signed(forged, publisher="crm", secret="test-secret-crm-erp")
    result = await erp_receiver.receive(headers, body)
    assert (result.status_code, result.body) == (400, {"error": "foreign_type"})
    assert seen == []


async def test_erp_may_not_publish_identity_or_crm(clock: Clock, subscriptions_file: Path, seen: list[Event]) -> None:
    registry = HandlerRegistry()

    @registry.subscribe("uz.railtech.*.v1")
    async def on_any(event: Event) -> None:
        seen.append(event)

    crm = MemoryReceiver(make_config("crm", clock, subscriptions_file), registry=registry)
    for rel in ("identity/user.updated.v1", "crm/client.updated.v1"):
        forged = envelope(rel, source="rt://erp")
        headers, body = signed(forged, publisher="erp")
        assert (await crm.receive(headers, body)).status_code == 400, rel
    headers, body = signed(envelope("erp/quote.sent.v1"), publisher="erp")
    assert (await crm.receive(headers, body)).status_code == 200
    assert [e.type for e in seen] == ["uz.railtech.erp.quote.sent.v1"]


async def test_publisher_domains_are_data(clock: Clock, subscriptions_file: Path) -> None:
    registry = HandlerRegistry()
    own = {**DEFAULT_PUBLISHER_DOMAINS, "erp": frozenset({"erp", "crm"})}
    receiver = MemoryReceiver(make_config("crm", clock, subscriptions_file, publisher_domains=own), registry=registry)
    forged = envelope("crm/client.updated.v1", source="rt://erp")
    headers, body = signed(forged, publisher="erp")
    assert (await receiver.receive(headers, body)).status_code == 200  # skipped: обработчика нет, но отказа нет


def test_default_table_and_unknown_publisher() -> None:
    assert DEFAULT_PUBLISHER_DOMAINS["crm"] == {"crm", "identity"}
    assert DEFAULT_PUBLISHER_DOMAINS["erp"] == {"erp"}
    assert DEFAULT_PUBLISHER_DOMAINS["eds"] == {"eds"}
    assert DEFAULT_PUBLISHER_DOMAINS["platform-bff"] == {"platform"}
    assert foreign_type("eds", "uz.railtech.eds.letter.resolved.v1", None) is None
    assert foreign_type("eds", "uz.railtech.erp.quote.sent.v1", None) is not None
    # издателя нет в таблице — только домен с его именем
    assert foreign_type("erp2", "uz.railtech.erp.quote.sent.v1", None) is not None
    assert foreign_type("erp", "not-a-type", None) is not None
