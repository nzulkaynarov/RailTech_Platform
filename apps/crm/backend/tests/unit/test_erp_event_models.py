"""Дискриминированные модели событий ERP → CRM против контракта (FIX-35, I-15, G-5).

Источник правды — `packages/contracts/events.schema.json` и примеры `examples/events` (по одному
на каждое из 22 событий; те же примеры — фикстуры тестов ERP). Проверяется, что CRM:

* знает ровно те типы событий, что описаны в схеме, и разбирает каждый пример в модель нужного
  класса с типизированным `payload` (класс тела называется как `$defs`-схема контракта);
* требует `deal` там, где его требует схема, и поля тела, которые схема объявляет обязательными;
* терпимо читает: лишние поля в конверте, в `deal`, в `actor` и в теле игнорирует;
* не принимает чужие значения перечислений и форматов (стадия, сумма, валюта, статус строки).
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.erp_events import (
    CODE_EVENT,
    KNOWN_EVENTS,
    REDACTED,
    DealRef,
    DeliveryLineDecision,
    ErpEventEnvelope,
    QuoteAcceptanceCodeRequested,
    QuoteOutcome,
    is_known_event,
    parse_event,
    redact_secrets,
)
from tests.seam_events import (
    deal_required,
    event_types,
    example_event,
    example_files,
    payload_def_name,
    required_payload_fields,
)

ALL_EVENTS = event_types()


def test_known_events_are_exactly_the_events_of_the_contract() -> None:
    assert set(KNOWN_EVENTS) == set(ALL_EVENTS)
    assert len(ALL_EVENTS) == 22
    assert set(example_files()) == set(ALL_EVENTS), "на каждое событие контракта — один пример"
    assert not is_known_event("warehouse.exploded")
    assert not is_known_event(None)


@pytest.mark.parametrize("event", ALL_EVENTS)
def test_every_example_is_parsed_into_its_own_typed_envelope(event: str) -> None:
    envelope = parse_event(example_event(event))
    assert isinstance(envelope, ErpEventEnvelope)
    assert envelope.event == event
    assert isinstance(envelope.payload, BaseModel)
    assert type(envelope.payload).__name__ == payload_def_name(event), (
        "класс тела события называется как схема контракта"
    )
    assert (envelope.deal is not None) == ("deal" in example_event(event))


@pytest.mark.parametrize("event", ALL_EVENTS)
def test_deal_is_required_exactly_where_the_schema_requires_it(event: str) -> None:
    body = example_event(event)
    body.pop("deal", None)
    if deal_required(event):
        with pytest.raises(ValidationError):
            parse_event(body)
    else:
        assert parse_event(body).deal is None


@pytest.mark.parametrize(
    ("event", "field"),
    [(event, field) for event in ALL_EVENTS for field in required_payload_fields(event)],
)
def test_required_payload_fields_of_the_schema_are_required(event: str, field: str) -> None:
    body = example_event(event)
    body["payload"].pop(field)
    with pytest.raises(ValidationError):
        parse_event(body)


@pytest.mark.parametrize(
    "field", ["version", "occurred_at", "erp_company_id", "crm_client_id", "actor"]
)
def test_required_envelope_fields_are_required(field: str) -> None:
    body = example_event("quote.sent")
    body.pop(field)
    with pytest.raises(ValidationError):
        parse_event(body)


@pytest.mark.parametrize("event", ALL_EVENTS)
def test_new_fields_are_ignored_everywhere(event: str) -> None:
    """Терпимый читатель: поле, которого CRM не знает, не даёт отказа и не попадает в модель."""
    body = example_event(event)
    body["brand_new_field"] = {"nested": 1}
    body["actor"]["brand_new_field"] = 1
    body["payload"]["brand_new_field"] = [1, 2]
    if "deal" in body:
        body["deal"]["brand_new_field"] = "x"
    envelope = parse_event(body)
    assert not hasattr(envelope, "brand_new_field")
    assert "brand_new_field" not in envelope.payload.model_dump()
    assert envelope.event == event


def test_unknown_event_is_not_parsed_by_the_discriminated_union() -> None:
    body = example_event("quote.sent")
    body["event"] = "warehouse.exploded"
    with pytest.raises(
        ValidationError, match=r"union_tag_invalid|does not match any of the expected tags"
    ):
        parse_event(body)


def test_version_other_than_one_is_refused() -> None:
    body = example_event("quote.sent")
    body["version"] = 2
    with pytest.raises(ValidationError):
        parse_event(body)


@pytest.mark.parametrize(
    ("event", "mutate"),
    [
        ("invoice.issued", lambda b: b["deal"].update(stage="CLOSED_WON")),
        ("invoice.issued", lambda b: b["deal"].update(amount="125000000")),
        ("invoice.issued", lambda b: b["deal"].update(currency="uzs")),
        ("invoice.issued", lambda b: b["payload"].update(amount="62500000")),
        ("invoice.issued", lambda b: b["payload"].update(due_date="24.10.2026")),
        ("quote.sent", lambda b: b["payload"].update(version=0)),
        ("contract.signed", lambda b: b["payload"].update(by="nobody")),
        ("delivery.status_changed", lambda b: b["payload"].update(status="lost")),
        ("invite.sent", lambda b: b["payload"].update(channels=[])),
        ("invite.sent", lambda b: b["payload"].update(channels=["sms"])),
        ("document.created", lambda b: b["payload"].update(kind="photo")),
        ("deal.stage_changed", lambda b: b["payload"].update(to="nowhere")),
        ("request.created", lambda b: b["payload"].update(source="fax")),
        ("quote.viewed", lambda b: b.update(occurred_at="not a date")),
        ("quote.viewed", lambda b: b["actor"].update(type="robot")),
    ],
)
def test_values_outside_the_contract_are_refused(event: str, mutate: Any) -> None:
    body = example_event(event)
    mutate(body)
    with pytest.raises(ValidationError):
        parse_event(body)


def test_deal_ref_amount_may_be_null() -> None:
    """FIX-29: сумма сделки — `null`, пока КП клиенту не отправлялось."""
    body = example_event("request.created")
    body["deal"]["amount"] = None
    envelope = parse_event(body)
    assert isinstance(envelope.deal, DealRef)
    assert envelope.deal.amount is None


def test_stage_changed_keeps_the_from_alias_in_a_round_trip() -> None:
    body = example_event("deal.stage_changed")
    envelope = parse_event(body)
    dumped = envelope.payload.model_dump(mode="json", by_alias=True)
    assert dumped["from"] == body["payload"]["from"]
    assert dumped["to"] == body["payload"]["to"]


# ── Приёмка и замечание по строке поставки: правила тела и конверта ─────────────────────


def test_line_decision_rules() -> None:
    accepted = example_event("delivery.line_accepted")
    disputed = example_event("delivery.line_disputed")
    assert isinstance(parse_event(accepted).payload, DeliveryLineDecision)

    with pytest.raises(ValidationError, match=r"actor\.type=client"):
        parse_event({**accepted, "actor": {"type": "staff"}})
    with pytest.raises(ValidationError, match="does not match payload status"):
        parse_event({**accepted, "event": "delivery.line_disputed"})
    with pytest.raises(ValidationError, match="remark is required"):
        parse_event({**disputed, "payload": {**disputed["payload"], "remark": "  "}})
    with pytest.raises(ValidationError):
        parse_event({**disputed, "payload": {**disputed["payload"], "remark": "я" * 2001}})
    without_deal = {k: v for k, v in accepted.items() if k != "deal"}
    with pytest.raises(ValidationError):
        parse_event(without_deal)


# ── Шов 0.3.0 (FIX-60): код акцепта и контакт в исходах КП ───────────────────────────────────


@pytest.mark.parametrize("code", ["12", "1234567890123", "12a456", "", " 123456", "١٢٣٤٥٦"])
def test_acceptance_code_must_be_four_to_twelve_ascii_digits(code: str) -> None:
    body = example_event(CODE_EVENT)
    body["payload"]["code"] = code
    with pytest.raises(ValidationError):
        parse_event(body)


def test_acceptance_code_is_a_secret_in_repr_and_dumps() -> None:
    body = example_event(CODE_EVENT)
    body["payload"]["code"] = "482913"
    envelope = parse_event(body)
    assert isinstance(envelope.payload, QuoteAcceptanceCodeRequested)
    assert envelope.payload.code.get_secret_value() == "482913"
    for rendered in (
        repr(envelope),
        str(envelope.payload),
        envelope.model_dump_json(),
        str(envelope.payload.model_dump(mode="json")),
    ):
        assert "482913" not in rendered


def test_redact_secrets_hides_only_the_code_and_leaves_the_original_untouched() -> None:
    body = example_event(CODE_EVENT)
    body["payload"]["code"] = "482913"
    redacted = redact_secrets(body)
    assert redacted["payload"]["code"] == REDACTED
    assert {k: v for k, v in redacted["payload"].items() if k != "code"} == {
        k: v for k, v in body["payload"].items() if k != "code"
    }
    assert body["payload"]["code"] == "482913", "исходное тело не меняется — по нему идёт доставка"
    # тип события по заголовку тоже считается: тело с расхождением не уносит код в журнал
    mismatched = {**body, "event": "quote.sent"}
    assert redact_secrets(mismatched, CODE_EVENT)["payload"]["code"] == REDACTED
    other = example_event("quote.sent")
    assert redact_secrets(other) is other


def test_outcome_contacts_are_optional_and_unknown_ids_do_not_matter() -> None:
    """`erp_contact_id`/`crm_contact_id` необязательны: действие не из Cabinet их не несёт."""
    body = example_event("quote.accepted")
    assert isinstance(parse_event(body).payload, QuoteOutcome)
    for field in ("erp_contact_id", "crm_contact_id"):
        body["payload"].pop(field, None)
    payload = parse_event(body).payload
    assert isinstance(payload, QuoteOutcome)
    assert (payload.erp_contact_id, payload.crm_contact_id) == (None, None)
    body["payload"]["crm_contact_id"] = None
    nulled = parse_event(body).payload
    assert isinstance(nulled, QuoteOutcome)
    assert nulled.crm_contact_id is None
