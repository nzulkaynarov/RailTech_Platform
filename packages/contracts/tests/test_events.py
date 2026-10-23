"""Контракт событий rt_bus: схемы валидны, каждый тип имеет пример, пример проходит конверт и схему типа,
AsyncAPI и файлы типов совпадают в обе стороны, подписки по схеме, сгенерированные модели покрывают все типы."""

from __future__ import annotations

import copy
import fnmatch
from pathlib import Path

import pytest
import yaml
from contracts_events import (
    BUS,
    CONTRACTS,
    DOMAIN_SOURCE,
    ENVELOPE,
    EVENTS,
    EventType,
    event_types,
    load_json,
    registry,
    schema_files,
)
from events_compat import deref, working_tree
from jsonschema import Draft202012Validator, FormatChecker

TYPES = event_types()
IDS = [t.name for t in TYPES]
REGISTRY = registry()
FORMATS = FormatChecker()


def validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=REGISTRY, format_checker=FORMATS)


def type_validator(t: EventType) -> Draft202012Validator:
    return validator(load_json(t.path))


ENVELOPE_VALIDATOR = validator(load_json(ENVELOPE))
ASYNCAPI = yaml.safe_load((EVENTS / "asyncapi.yaml").read_text(encoding="utf-8"))


def test_types_present() -> None:
    domains = {t.domain for t in TYPES}
    assert {"erp", "crm", "identity"} <= domains
    assert len([t for t in TYPES if t.domain == "erp"]) == 22


@pytest.mark.parametrize("path", schema_files(), ids=lambda p: p.relative_to(CONTRACTS).as_posix())
def test_schema_is_valid_2020_12(path: Path) -> None:
    doc = load_json(path)
    Draft202012Validator.check_schema(doc)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    rel = path.relative_to(CONTRACTS).as_posix()
    assert doc["$id"] == f"https://railtech.uz/contracts/{rel}", "$id повторяет путь файла — относительные $ref"


def test_all_refs_resolve() -> None:
    tree = working_tree()
    for path, doc in tree.items():
        deref(doc, path, tree)


def test_examples_and_types_match() -> None:
    examples = {(p.parent.parent.name, p.name) for p in EVENTS.glob("*/examples/*.json")}
    expected = {(t.domain, f"{t.stem}.json") for t in TYPES}
    assert examples == expected, "у каждого типа ровно один пример, примеров без типа нет"


@pytest.mark.parametrize("t", TYPES, ids=IDS)
def test_example_passes_envelope_and_type(t: EventType) -> None:
    env = load_json(t.example)
    errors = [e.message for e in ENVELOPE_VALIDATOR.iter_errors(env)]
    assert not errors, errors
    assert env["type"] == t.name
    assert env["source"] == t.source == DOMAIN_SOURCE[t.domain]
    assert env["dataschema"] == t.dataschema
    assert env["time"].endswith("Z"), "отправитель пишет time в UTC"
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in type_validator(t).iter_errors(env["data"])]
    assert not errors, errors


@pytest.mark.parametrize("t", TYPES, ids=IDS)
def test_type_schema_rejects_missing_required_and_unknown_field(t: EventType) -> None:
    v = type_validator(t)
    data = load_json(t.example)["data"]
    schema = load_json(t.path)
    broken = copy.deepcopy(data)
    del broken[schema["required"][0]]
    assert not v.is_valid(broken)
    assert not v.is_valid({**data, "unexpected_field": 1}), "отправитель строгий: additionalProperties false"


def test_envelope_rules() -> None:
    env = load_json(TYPES[0].example)
    assert ENVELOPE_VALIDATOR.is_valid({**env, "myext": "x"}), "расширения CloudEvents допускаются"
    for bad in (
        {**env, "Bad_Ext": "x"},
        {**env, "specversion": "0.3"},
        {**env, "id": "not-a-uuid"},
        {**env, "type": "uz.railtech.erp.quote.sent"},
        {**env, "source": "erp"},
        {**env, "datacontenttype": "text/plain"},
        {**env, "traceparent": "zz"},
        {k: v for k, v in env.items() if k != "correlationid"},
        {k: v for k, v in env.items() if k != "tenant"},
    ):
        assert not ENVELOPE_VALIDATOR.is_valid(bad), bad


def test_line_disputed_requires_remark() -> None:
    t = next(t for t in TYPES if t.name == "uz.railtech.erp.delivery.line_disputed.v1")
    data = load_json(t.example)["data"]
    broken = copy.deepcopy(data)
    broken["payload"]["remark"] = None
    assert not type_validator(t).is_valid(broken)


def test_erp_types_cover_legacy_schema() -> None:
    """Все 22 события events.schema.json (устаревает, L7) есть как uz.railtech.erp.<тип>.v1."""
    legacy = set(load_json(CONTRACTS / "events.schema.json")["$defs"]["EventType"]["enum"])
    assert {f"{t.entity}.{t.action}" for t in TYPES if t.domain == "erp" and t.version == 1} == legacy


def _property_names(node: object) -> set[str]:
    if isinstance(node, dict):
        names = set(node.get("properties", {})) if isinstance(node.get("properties"), dict) else set()
        return names.union(*(_property_names(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_property_names(v) for v in node))
    return set()


def test_no_secrets_in_crm_and_identity_events() -> None:
    """Пароли, токены, хэши и секреты в событиях CRM и идентичности не публикуются (ADR-0015, CONTRACTS §0)."""
    tree = working_tree()
    for t in TYPES:
        if t.domain not in ("crm", "identity"):
            continue
        rel = t.path.relative_to(CONTRACTS).as_posix()
        names = _property_names(deref(tree[rel], rel, tree))
        secret_like = ("password", "token", "secret", "hash")
        leaked = [n for n in names if n in ("code", "otp") or any(w in n for w in secret_like)]
        assert not leaked, f"{t.name}: {leaked}"


# ─── AsyncAPI ─────────────────────────────────────────────────────────────────────────────────


def test_asyncapi_channels_match_types() -> None:
    assert ASYNCAPI["asyncapi"].startswith("3.")
    names = {t.name for t in TYPES}
    assert set(ASYNCAPI["channels"]) == names
    assert set(ASYNCAPI["components"]["messages"]) == names
    assert {op["channel"]["$ref"].removeprefix("#/channels/") for op in ASYNCAPI["operations"].values()} == names


@pytest.mark.parametrize("t", TYPES, ids=IDS)
def test_asyncapi_message_points_to_type_schema(t: EventType) -> None:
    channel = ASYNCAPI["channels"][t.name]
    assert channel["address"] == t.name
    msg = ASYNCAPI["components"]["messages"][t.name]
    assert msg["contentType"] == "application/cloudevents+json"
    envelope_ref, overlay = msg["payload"]["schema"]["allOf"]
    assert envelope_ref == {"$ref": "./envelope.v1.json"}
    props = overlay["properties"]
    assert props["type"]["const"] == t.name
    assert props["source"]["const"] == t.source
    assert props["dataschema"]["const"] == t.dataschema
    assert props["data"]["$ref"] == f"./{t.domain}/{t.stem}.json"
    assert (EVENTS / props["data"]["$ref"]).resolve() == t.path.resolve()


# ─── подписки ─────────────────────────────────────────────────────────────────────────────────

SUBSCRIPTIONS = yaml.safe_load((BUS / "subscriptions.yaml").read_text(encoding="utf-8"))


def test_subscriptions_match_schema() -> None:
    v = Draft202012Validator(load_json(BUS / "subscriptions.schema.json"), format_checker=FORMATS)
    errors = [e.message for e in v.iter_errors(SUBSCRIPTIONS)]
    assert not errors, errors


def test_subscriptions_are_meaningful() -> None:
    names = [s["name"] for s in SUBSCRIPTIONS["subscribers"]]
    assert len(names) == len(set(names)), "имя подписчика уникально"
    known = [t.name for t in TYPES]
    for s in SUBSCRIPTIONS["subscribers"]:
        for mask in s["types"]:
            matched = [n for n in known if fnmatch.fnmatchcase(n, mask)]
            assert matched, f"{s['name']}: маска {mask} не совпадает ни с одним типом"
            own = [t for t in TYPES if t.name in matched and t.source == f"rt://{s['name']}"]
            assert not own, f"{s['name']}: подписан на свои события {own} — издатель себе не доставляет"


def test_initial_subscriptions_v1() -> None:
    subs = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}
    assert set(subs) == {"crm", "erp", "platform-bff"}
    assert subs["crm"]["types"] == ["uz.railtech.erp.*.v1"]
    assert subs["crm"]["endpoint"] == "http://crm-api:8000/bus/v1/events"
    assert subs["erp"]["endpoint"] == "http://erp-backend:8000/bus/v1/events"
    erp_gets = sorted(t.name for t in TYPES if any(fnmatch.fnmatchcase(t.name, m) for m in subs["erp"]["types"]))
    assert erp_gets == [
        "uz.railtech.crm.client.updated.v1",
        "uz.railtech.crm.contact.created.v1",
        "uz.railtech.crm.contact.deleted.v1",
        "uz.railtech.crm.contact.updated.v1",
    ]


def test_platform_bff_subscription_b5() -> None:
    """BFF Платформы (B5): события ERP, лидов CRM и сотрудников; адрес — внутри сети compose."""
    bff = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}["platform-bff"]
    assert bff["endpoint"] == "http://platform-bff:8000/bus/v1/events"
    assert bff["endpoint_env"] == "RT_BUS_ENDPOINT_PLATFORM_BFF"
    gets = {t.name for t in TYPES if any(fnmatch.fnmatchcase(t.name, m) for m in bff["types"])}
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.erp.")} <= gets
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.crm.lead.")} <= gets
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.identity.user.")} <= gets
    assert not {n for n in gets if n.startswith(("uz.railtech.crm.client.", "uz.railtech.crm.contact."))}


# ─── сгенерированный пакет rt-contracts ────────────────────────────────────────────────────────


def test_generated_models_cover_types() -> None:
    from rt_contracts.events import TYPES as MODELS

    assert set(MODELS) == {t.name for t in TYPES}


@pytest.mark.parametrize("t", TYPES, ids=IDS)
def test_generated_models_parse_examples(t: EventType) -> None:
    from rt_contracts.events import TYPES as MODELS
    from rt_contracts.events import Envelope

    env = Envelope.model_validate(load_json(t.example))
    assert env.type == t.name
    data = MODELS[env.type].model_validate(env.data)
    # Читатель терпимый: неизвестное поле новой версии схемы не ломает модель.
    MODELS[env.type].model_validate({**env.data, "future_optional_field": 1})
    assert data.model_dump(mode="json", by_alias=True, exclude_unset=True) == env.data
