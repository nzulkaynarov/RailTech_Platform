"""Конверт (L1), тип (L2), реестр схем: строгая проверка издателя, терпимая — приёмника (L10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rt_bus import EventValidationError, SchemaRegistry, UnknownEventTypeError, correlation, parse_type
from rt_bus.core import BusCore
from rt_bus.envelope import Event
from rt_bus.errors import ConfigError
from rt_bus.schemas import CONTRACTS_DIR_ENV, resolve_contracts_dir

from .conftest import EVENTS_DIR, T0, Clock, example, example_data, make_config


@pytest.fixture
def schemas() -> SchemaRegistry:
    return SchemaRegistry(EVENTS_DIR)


def test_type_parsing_and_paths() -> None:
    t = parse_type("uz.railtech.erp.delivery.line_accepted.v1")
    assert (t.domain, t.entity, t.action, t.version) == ("erp", "delivery", "line_accepted", 1)
    assert t.schema_path == "erp/delivery.line_accepted.v1.json"
    assert t.dataschema == "rt://contracts/events/erp/delivery.line_accepted/v1"
    for bad in [
        "erp.quote.sent",
        "uz.railtech.erp.quote.sent",
        "uz.railtech.sales.quote.sent.v1",
        "uz.railtech.erp.q.s.v0",
    ]:
        with pytest.raises(UnknownEventTypeError):
            parse_type(bad)


def test_every_fixture_example_passes(schemas: SchemaRegistry) -> None:
    assert schemas.check_examples() == {}
    assert "uz.railtech.erp.quote.sent.v1" in schemas.types
    assert not any(t.endswith("_defs.v1") for t in schemas.types)


def test_build_event_fills_envelope(tmp_path: Path, subscriptions_file: Path) -> None:
    core = BusCore(make_config("erp", Clock(), subscriptions_file))
    event = core.build_event("uz.railtech.erp.quote.sent.v1", example_data("erp/quote.sent.v1"), subject="D-2026-0905")
    envelope = event.to_dict()
    assert envelope["specversion"] == "1.0"
    assert envelope["source"] == "rt://erp"
    assert envelope["time"] == "2026-10-23T09:00:00.000Z"
    assert envelope["dataschema"] == "rt://contracts/events/erp/quote.sent/v1"
    assert envelope["tenant"] == "railtech"
    assert envelope["datacontenttype"] == "application/json"
    assert "traceparent" not in envelope
    assert len(envelope["correlationid"]) == 36  # нет контекста — новый UUID
    assert core.schemas.validate_envelope(envelope) == []


def test_build_event_takes_correlation_from_context(subscriptions_file: Path) -> None:
    core = BusCore(make_config("erp", Clock(), subscriptions_file))
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with correlation("req-42", tp):
        event = core.build_event("uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
    assert event.correlationid == "req-42"
    assert event.traceparent == tp


def test_publisher_is_strict(subscriptions_file: Path) -> None:
    core = BusCore(make_config("erp", Clock(), subscriptions_file))
    data = example_data("erp/quote.sent.v1")
    with pytest.raises(EventValidationError, match="Additional"):
        core.build_event("uz.railtech.erp.quote.sent.v1", {**data, "extra_field": 1})
    broken = {**data}
    del broken["deal"]
    with pytest.raises(EventValidationError, match="deal"):
        core.build_event("uz.railtech.erp.quote.sent.v1", broken)
    with pytest.raises(UnknownEventTypeError):
        core.build_event("uz.railtech.erp.quote.sent.v9", data)
    with pytest.raises(EventValidationError):
        core.build_event("uz.railtech.erp.quote.sent.v1", {"when": T0})  # не JSON


def test_receiver_tolerates_additional_properties_only(schemas: SchemaRegistry) -> None:
    data = example_data("erp/quote.sent.v1")
    extended = {**data, "new_optional": "x", "deal": {**data["deal"], "new_nested": True}}
    assert schemas.validate_data("uz.railtech.erp.quote.sent.v1", extended, tolerant=True) == []
    assert schemas.validate_data("uz.railtech.erp.quote.sent.v1", extended, tolerant=False)
    wrong_type = {**data, "erp_company_id": "118"}
    assert schemas.validate_data("uz.railtech.erp.quote.sent.v1", wrong_type, tolerant=True)
    bad_enum = {**data, "deal": {**data["deal"], "stage": "unknown"}}
    assert schemas.validate_data("uz.railtech.erp.quote.sent.v1", bad_enum, tolerant=True)


def test_envelope_checks(schemas: SchemaRegistry) -> None:
    good = example("erp/quote.sent.v1")
    assert schemas.validate_envelope(good) == []
    assert schemas.validate_envelope({**good, "myext": "ok"}) == []  # расширение CloudEvents
    assert schemas.validate_envelope({**good, "dataschema": "rt://contracts/events/erp/quote.viewed/v1"})
    assert schemas.validate_envelope({**good, "time": "2026-10-13T04:15:00"})  # без пояса
    missing = dict(good)
    del missing["correlationid"]
    assert schemas.validate_envelope(missing)
    assert schemas.validate_envelope([1, 2])
    assert Event.from_dict({**good, "myext": "ok"}).extensions == {"myext": "ok"}


def test_event_roundtrip() -> None:
    envelope = example("crm/client.updated.v1")
    assert json.loads(Event.from_dict(envelope).to_json()) == envelope


def test_contracts_dir_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONTRACTS_DIR_ENV, str(EVENTS_DIR))
    assert resolve_contracts_dir() == EVENTS_DIR
    monkeypatch.setenv(CONTRACTS_DIR_ENV, str(tmp_path))
    with pytest.raises(ConfigError):
        resolve_contracts_dir()


def test_publisher_error_does_not_leak_secret(subscriptions_file: Path) -> None:
    core = BusCore(make_config("erp", Clock(), subscriptions_file))
    data = example_data("erp/quote.acceptance_code_requested.v1")
    data["payload"]["code"] = 482913
    with pytest.raises(EventValidationError) as raised:
        core.build_event("uz.railtech.erp.quote.acceptance_code_requested.v1", data)
    assert "482913" not in str(raised.value)
    assert all("482913" not in e for e in raised.value.errors)
