"""События ERP → CRM против контракта rt_bus: модели `rt_contracts`, схемы, подписки (B4, G-5).

Источник правды — `packages/contracts/events/` и примеры полного конверта рядом (по одному на каждый
из 22 типов ERP; те же файлы — фикстуры ERP и самой шины). Ручной копии схем в CRM нет. Проверяется:

* CRM подписана ровно на те типы ERP, что описаны в контракте (кроме кода акцепта — он inline);
* каждый пример разбирается в модель нужного типа, имя события и время берутся из конверта;
* приёмник проверяет `data` терпимо: лишнее поле — не отказ, чужие значения перечислений и форматов,
  потерянные обязательные поля — отказ (422), на уровне схем библиотеки;
* код акцепта: маска в хранимом конверте, секретное поле объявлено, пример — не настоящий код.
"""

from typing import Any

import pytest
from pydantic import ValidationError
from rt_bus import Event, SchemaRegistry
from rt_bus.handlers import default_registry
from rt_bus.masking import DEFAULT_SECRET_FIELDS
from rt_contracts.events import TYPES
from rt_contracts.events.erp import QuoteSentV1

from app.bus import handlers  # noqa: F401 — регистрирует обработчики
from app.bus.erp_event import CODE_TYPE, NOT_FOR_CRM, erp_types, parse_erp_event, plain
from tests.bus_events import event_types, example_envelope, example_types

#: Типы ERP, которые принимает CRM (без адресованных EDS — `NOT_FOR_CRM`).
ALL_TYPES = [t for t in event_types("erp") if t not in NOT_FOR_CRM]
REGISTRY = SchemaRegistry()


def event_of(event_type: str, **changes: Any) -> Event:
    return Event.from_dict({**example_envelope(event_type), **changes})


def test_the_contract_has_twenty_two_erp_types_with_one_example_each() -> None:
    assert len(ALL_TYPES) == 22
    examples = set(example_types("erp"))
    assert examples == set(event_types("erp")), "на каждое событие контракта — один пример"


def test_the_crm_listens_to_exactly_the_erp_events_of_the_contract_except_the_code() -> None:
    assert set(erp_types()) == set(ALL_TYPES) - {CODE_TYPE}
    assert len(erp_types()) == 21
    for event_type in ALL_TYPES:
        matched = default_registry.match(event_type)
        assert len(matched) == 1, event_type
        assert matched[0].inline is (event_type == CODE_TYPE)


def test_handlers_do_not_listen_to_other_domains_or_future_versions() -> None:
    assert default_registry.match("uz.railtech.crm.client.updated.v1") == []
    assert default_registry.match("uz.railtech.erp.quote.sent.v2") == []
    assert default_registry.match("uz.railtech.erp.warehouse.exploded.v1") == []
    for event_type in NOT_FOR_CRM:
        assert default_registry.match(event_type) == [], "тип для EDS: CRM не обрабатывает"


@pytest.mark.parametrize("event_type", ALL_TYPES)
def test_every_example_is_parsed_into_its_own_model(event_type: str) -> None:
    env = parse_erp_event(event_of(event_type))
    assert isinstance(env.data, TYPES[event_type])
    assert event_type.endswith(f".{env.event}.v1")
    assert env.occurred_at.tzinfo is not None
    assert env.crm_client_id == example_envelope(event_type)["data"]["crm_client_id"]
    assert (env.deal is not None) == ("deal" in example_envelope(event_type)["data"])


@pytest.mark.parametrize("event_type", ALL_TYPES)
def test_every_example_passes_the_schema_the_way_the_receiver_checks_it(event_type: str) -> None:
    data = example_envelope(event_type)["data"]
    assert REGISTRY.validate_data(event_type, data, tolerant=False) == []
    assert REGISTRY.validate_data(event_type, data, tolerant=True) == []


@pytest.mark.parametrize("event_type", ALL_TYPES)
def test_new_fields_are_ignored_everywhere(event_type: str) -> None:
    """Терпимый читатель: поле, которого CRM не знает, не даёт отказа и не попадает в модель."""
    envelope = example_envelope(event_type)
    data = envelope["data"]
    data["brand_new_field"] = {"nested": 1}
    data["actor"]["brand_new_field"] = 1
    data["payload"]["brand_new_field"] = [1, 2]
    if "deal" in data:
        data["deal"]["brand_new_field"] = "x"
    assert REGISTRY.validate_data(event_type, data, tolerant=True) == []
    assert REGISTRY.validate_data(event_type, data, tolerant=False), "отправитель строгий"
    env = parse_erp_event(Event.from_dict(envelope))
    assert "brand_new_field" not in env.payload.model_dump()


def test_a_type_of_another_domain_or_version_is_not_an_erp_event() -> None:
    with pytest.raises(ValueError, match="not an ERP event type"):
        parse_erp_event(
            event_of("uz.railtech.erp.quote.sent.v1", type="uz.railtech.erp.quote.sent.v2")
        )
    crm_event = Event.from_dict(example_envelope("uz.railtech.crm.client.updated.v1"))
    with pytest.raises(ValueError, match="not an ERP event type"):
        parse_erp_event(crm_event)


def test_a_body_that_does_not_fit_the_model_is_refused_by_the_parser() -> None:
    envelope = example_envelope("uz.railtech.erp.quote.sent.v1")
    del envelope["data"]["payload"]["erp_quote_id"]
    with pytest.raises(ValidationError):
        parse_erp_event(Event.from_dict(envelope))


@pytest.mark.parametrize("field", ["erp_company_id", "crm_client_id", "actor", "payload", "deal"])
def test_required_fields_of_the_envelope_data_are_required(field: str) -> None:
    data = example_envelope("uz.railtech.erp.invoice.issued.v1")["data"]
    data.pop(field)
    assert REGISTRY.validate_data("uz.railtech.erp.invoice.issued.v1", data, tolerant=True)


def test_deal_is_optional_exactly_where_the_schema_says_so() -> None:
    for event_type in ("uz.railtech.erp.document.created.v1", "uz.railtech.erp.invite.sent.v1"):
        data = example_envelope(event_type)["data"]
        data.pop("deal", None)
        assert REGISTRY.validate_data(event_type, data, tolerant=True) == []
        assert parse_erp_event(event_of(event_type, data=data)).deal is None


@pytest.mark.parametrize(
    ("event_type", "mutate"),
    [
        ("invoice.issued", lambda d: d["deal"].update(stage="CLOSED_WON")),
        ("invoice.issued", lambda d: d["deal"].update(amount="125000000")),
        ("invoice.issued", lambda d: d["deal"].update(currency="uzs")),
        ("invoice.issued", lambda d: d["payload"].update(amount="62500000")),
        ("invoice.issued", lambda d: d["payload"].update(due_date="24.10.2026")),
        ("quote.sent", lambda d: d["payload"].update(version=0)),
        ("contract.signed", lambda d: d["payload"].update(by="nobody")),
        ("delivery.status_changed", lambda d: d["payload"].update(status="lost")),
        ("invite.sent", lambda d: d["payload"].update(channels=[])),
        ("invite.sent", lambda d: d["payload"].update(channels=["sms"])),
        ("document.created", lambda d: d["payload"].update(kind="photo")),
        ("deal.stage_changed", lambda d: d["payload"].update(to="nowhere")),
        ("request.created", lambda d: d["payload"].update(source="fax")),
        ("quote.viewed", lambda d: d["actor"].update(type="robot")),
    ],
)
def test_values_outside_the_contract_are_refused_by_the_receiver_schema(
    event_type: str, mutate: Any
) -> None:
    full = f"uz.railtech.erp.{event_type}.v1"
    data = example_envelope(full)["data"]
    mutate(data)
    assert REGISTRY.validate_data(full, data, tolerant=True), "422 у приёмника"


def test_deal_ref_amount_may_be_null() -> None:
    """FIX-29: сумма сделки — `null`, пока КП клиенту не отправлялось."""
    data = example_envelope("uz.railtech.erp.request.created.v1")["data"]
    data["deal"]["amount"] = None
    assert REGISTRY.validate_data("uz.railtech.erp.request.created.v1", data, tolerant=True) == []
    env = parse_erp_event(event_of("uz.railtech.erp.request.created.v1", data=data))
    assert env.deal is not None
    assert env.deal.amount is None


def test_stage_changed_keeps_the_from_alias_in_a_round_trip() -> None:
    envelope = example_envelope("uz.railtech.erp.deal.stage_changed.v1")
    env = parse_erp_event(Event.from_dict(envelope))
    dumped = env.payload.model_dump(mode="json", by_alias=True)
    assert dumped["from"] == envelope["data"]["payload"]["from"]
    assert dumped["to"] == envelope["data"]["payload"]["to"]


def test_plain_unwraps_amounts_and_enums() -> None:
    env = parse_erp_event(event_of("uz.railtech.erp.quote.sent.v1"))
    assert isinstance(env.data, QuoteSentV1)
    assert env.deal is not None
    assert plain(env.deal.amount) == "125000000.00"
    assert plain(env.deal.stage) == "quote_sent"
    assert plain("x") == "x"


# ── Приёмка и замечание по строке поставки: правила тела ────────────────────────────────────────


def test_line_decision_rules() -> None:
    accepted = "uz.railtech.erp.delivery.line_accepted.v1"
    disputed = "uz.railtech.erp.delivery.line_disputed.v1"

    data = example_envelope(disputed)["data"]
    data["payload"]["remark"] = "я" * 2001
    assert REGISTRY.validate_data(disputed, data, tolerant=True), "замечание длиннее 2000"

    data = example_envelope(accepted)["data"]
    data.pop("deal")
    assert REGISTRY.validate_data(accepted, data, tolerant=True), "сделка обязательна"

    data = example_envelope(accepted)["data"]
    data["actor"] = {"type": "staff", "name": "М"}
    assert REGISTRY.validate_data(accepted, data, tolerant=True), "решает клиент"


# ── Шов 0.3.0 (FIX-60): код акцепта и контакт в исходах КП ───────────────────────────────────


@pytest.mark.parametrize("code", ["12", "1234567890123", "12a456", "", " 123456", "١٢٣٤٥٦"])
def test_acceptance_code_must_be_four_to_twelve_ascii_digits(code: str) -> None:
    data = example_envelope(CODE_TYPE)["data"]
    data["payload"]["code"] = code
    assert REGISTRY.validate_data(CODE_TYPE, data, tolerant=True)


def test_the_code_field_is_declared_secret_for_the_bus() -> None:
    assert DEFAULT_SECRET_FIELDS[CODE_TYPE] == ("payload.code",)


def test_the_example_of_the_contract_carries_a_code_that_is_not_a_real_one() -> None:
    assert example_envelope(CODE_TYPE)["data"]["payload"]["code"] == "000000"


def test_outcome_contacts_are_optional_and_unknown_ids_do_not_matter() -> None:
    """`erp_contact_id`/`crm_contact_id` необязательны: действие не из Cabinet их не несёт."""
    event_type = "uz.railtech.erp.quote.accepted.v1"
    data = example_envelope(event_type)["data"]
    for field in ("erp_contact_id", "crm_contact_id"):
        data["payload"].pop(field, None)
    assert REGISTRY.validate_data(event_type, data, tolerant=True) == []
    payload = parse_erp_event(event_of(event_type, data=data)).payload
    assert (payload.erp_contact_id, payload.crm_contact_id) == (None, None)
