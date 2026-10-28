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
    assert {"erp", "crm", "identity", "eds"} <= domains
    assert len([t for t in TYPES if t.domain == "erp"]) == 24


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


ERP_EVENTS = {
    "act.accepted",
    "act.issued",
    "act.returned",
    "contract.signed",
    "deal.lost",
    "deal.stage_changed",
    "deal.won",
    "delivery.eta_changed",
    "delivery.line_accepted",
    "delivery.line_disputed",
    "delivery.status_changed",
    "document.created",
    "invite.sent",
    "invoice.issued",
    "invoice.overdue",
    "invoice.paid",
    "quote.acceptance_code_requested",
    "quote.accepted",
    "quote.rejected",
    "quote.sent",
    "quote.viewed",
    "request.created",
}


#: Новые типы ERP после бывшего вебхука: волна 12 (EDS-03) — КП готово к одобрению директором в EDS.
ERP_EVENTS_C1 = {"quote.ready_for_approval"}

#: Волна 16 (D1-9): приглашение контакта в Cabinet через бот CRM — ERP в Telegram не пишет.
ERP_EVENTS_D1 = {"invite.requested"}


def test_erp_types_are_the_22_events_of_the_former_webhook_and_the_c1_ones() -> None:
    """22 события бывшего вебхука (events.schema.json удалён в B4) — по-прежнему uz.railtech.erp.<тип>.v1; плюс C1."""
    erp = {f"{t.entity}.{t.action}" for t in TYPES if t.domain == "erp" and t.version == 1}
    assert erp == ERP_EVENTS | ERP_EVENTS_C1 | ERP_EVENTS_D1


EDS_EVENTS = {
    "letter.registered",
    "letter.resolved",
    "letter.returned",
    "letter.rejected",
    "document.registered",
    "document.archived",
    "approval.requested",
    "approval.decided",
}


def test_eds_types_are_those_of_the_runbook() -> None:
    """Волна 12 §2.4: восемь типов uz.railtech.eds.*.v1, издатель rt://eds."""
    eds = [t for t in TYPES if t.domain == "eds"]
    assert {f"{t.entity}.{t.action}" for t in eds} == EDS_EVENTS
    assert {t.source for t in eds} == {"rt://eds"}


def _eds_example(name: str) -> dict:
    return copy.deepcopy(load_json(EVENTS / "eds" / "examples" / f"{name}.v1.json")["data"])


def _eds_validator(name: str) -> Draft202012Validator:
    return validator(load_json(EVENTS / "eds" / f"{name}.v1.json"))


@pytest.mark.parametrize("decision", ["return", "reject"])
def test_approval_decided_requires_a_comment_to_return_or_reject(decision: str) -> None:
    v = _eds_validator("approval.decided")
    data = _eds_example("approval.decided")
    route_status = "returned" if decision == "return" else "rejected"
    data.update(decision=decision, route_status=route_status, outgoing_number=None)
    data.pop("channels")
    for comment in (None, ""):
        assert not v.is_valid({**data, "comment": comment}), comment
    assert v.is_valid({**data, "comment": "Маржа ниже порога резолюции"})


def test_step_assignee_is_exactly_one_of_a_person_or_a_permission() -> None:
    v = _eds_validator("approval.requested")
    data = _eds_example("approval.requested")
    for assignee, ok in (
        ({"crm_user_id": None, "permission": "approvals.decide"}, True),
        ({"crm_user_id": 3, "permission": None}, True),
        ({"crm_user_id": 3, "permission": "approvals.decide"}, False),
        ({"crm_user_id": None, "permission": None}, False),
    ):
        data["step"]["assignee"] = assignee
        assert v.is_valid(data) is ok, assignee


def test_approval_object_of_a_quote_carries_the_erp_quote_and_a_document_carries_its_number() -> None:
    v = _eds_validator("approval.requested")
    data = _eds_example("approval.requested")
    broken = copy.deepcopy(data)
    del broken["approval"]["object"]["erp_quote_id"]
    assert not v.is_valid(broken)
    memo = copy.deepcopy(data)
    memo["approval"]["template"] = "memo"
    memo["approval"]["object"] = {"kind": "memo", "eds_document_id": "9b2f1f0e-6d7e-4a51-8d0a-3c1e2b4a5d60"}
    assert not v.is_valid(memo), "документ EDS — с номером реестра"
    memo["approval"]["object"]["number"] = "СЗ-2026/031"
    assert v.is_valid(memo)


@pytest.mark.parametrize(
    ("number", "ok"),
    [
        ("ВХ-104/26", True),
        ("ВХ-1/26", False),
        ("ВХ-104/2026", False),
        ("СЗ-2026/031", True),
        ("ЗЯ-2026/001", True),
        ("ОТ-2026/1200", True),
        ("ИСХ-082/26", True),
        ("СЗ-26/031", False),
        ("КП-2026/115", False),
    ],
)
def test_registry_numbers_follow_the_runbook_formats(number: str, ok: bool) -> None:
    """§2.1: ВХ-NNN/ГГ, ИСХ-NNN/ГГ, СЗ-ГГГГ/NNN, ЗЯ-ГГГГ/NNN, ОТ-ГГГГ/NNN; коммерческие номера (КП) — у ERP."""
    v = validator({"$ref": "https://railtech.uz/contracts/events/eds/_defs.v1.json#/$defs/RegistryNumber"})
    assert v.is_valid(number) is ok


def test_letter_resolved_carries_assignees_due_margin_and_erp_links() -> None:
    v = _eds_validator("letter.resolved")
    data = _eds_example("letter.resolved")
    assert {a["zone"] for a in data["resolution"]["assignees"]} == {"goods", "services"}
    for field in ("erp_request_id", "erp_deal_id", "deal_number"):
        broken = copy.deepcopy(data)
        del broken["links"][field]
        assert not v.is_valid(broken), field
    no_margin = copy.deepcopy(data)
    no_margin["resolution"]["min_margin_pct"] = None
    assert v.is_valid(no_margin), "резолюция без ограничения маржи"
    for bad in ("101", "-1", "15%", "12.345"):
        broken = copy.deepcopy(data)
        broken["resolution"]["min_margin_pct"] = bad
        assert not v.is_valid(broken), bad
    empty = copy.deepcopy(data)
    empty["resolution"]["assignees"] = []
    assert not v.is_valid(empty)


def test_identity_user_may_carry_eds_permission_codes() -> None:
    t = next(t for t in TYPES if t.name == "uz.railtech.identity.user.updated.v1")
    v = type_validator(t)
    data = load_json(t.example)["data"]
    assert data["user"]["permissions"]["eds"]
    without = copy.deepcopy(data)
    del without["user"]["permissions"]
    assert v.is_valid(without), "поле необязательное (v1, аддитивно)"
    future = copy.deepcopy(data)
    future["user"]["permissions"]["eds"] = ["payments.confirm"]
    assert v.is_valid(future), "новый код EDS не ломает identity v1 (шаблон, не перечень)"
    for bad in ("Letters.Read", "letters", "letters.read ", ""):
        broken = copy.deepcopy(data)
        broken["user"]["permissions"]["eds"] = [bad]
        assert not v.is_valid(broken), bad


def test_identity_user_may_carry_catalog_sections() -> None:
    """D1-8: `permissions.sections` — разделы каталога и уровень; аддитивно и необязательно."""
    t = next(t for t in TYPES if t.name == "uz.railtech.identity.user.updated.v1")
    v = type_validator(t)
    data = load_json(t.example)["data"]
    assert data["user"]["permissions"]["sections"]["erp.calc.goods"] == "full"
    without = copy.deepcopy(data)
    del without["user"]["permissions"]["sections"]
    assert v.is_valid(without), "поле необязательное: старый CRM его не публикует"
    empty = copy.deepcopy(data)
    empty["user"]["permissions"]["sections"] = {}
    assert v.is_valid(empty), "неактивный сотрудник — пусто"
    for bad in ("hidden", "FULL", "", None, True):
        broken = copy.deepcopy(data)
        broken["user"]["permissions"]["sections"]["eds.projects"] = bad
        assert not v.is_valid(broken), bad


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


def _gets(sub: dict) -> set[str]:
    return {t.name for t in TYPES if any(fnmatch.fnmatchcase(t.name, m) for m in sub["types"])}


def test_initial_subscriptions_v1() -> None:
    subs = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}
    assert set(subs) == {"crm", "erp", "platform-bff", "eds"}
    assert subs["crm"]["endpoint"] == "http://crm-api:8000/bus/v1/events"
    assert subs["erp"]["endpoint"] == "http://erp-backend:8000/bus/v1/events"
    assert sorted(_gets(subs["erp"])) == [
        "uz.railtech.crm.client.updated.v1",
        "uz.railtech.crm.contact.created.v1",
        "uz.railtech.crm.contact.deleted.v1",
        "uz.railtech.crm.contact.updated.v1",
        "uz.railtech.eds.approval.decided.v1",
        "uz.railtech.eds.letter.rejected.v1",
        "uz.railtech.eds.letter.resolved.v1",
    ]


def test_crm_gets_every_erp_event_except_the_quote_for_eds_approval() -> None:
    """CRM — все типы ERP, кроме quote.ready_for_approval: в нём себестоимость и маржа, адресат — EDS (волна 12)."""
    crm = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}["crm"]
    erp_types = {t.name for t in TYPES if t.domain == "erp"}
    assert _gets(crm) == erp_types - {"uz.railtech.erp.quote.ready_for_approval.v1"}


def test_eds_subscription_c1() -> None:
    """EDS (волна 12 §2.4): сотрудники, заявка ERP (связать письмо), КП на одобрение; адрес — внутри сети compose."""
    eds = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}["eds"]
    assert eds["endpoint"] == "http://eds-api:8000/bus/v1/events"
    assert eds["endpoint_env"] == "RT_BUS_ENDPOINT_EDS"
    assert _gets(eds) == {
        "uz.railtech.identity.user.created.v1",
        "uz.railtech.identity.user.updated.v1",
        "uz.railtech.identity.user.deactivated.v1",
        "uz.railtech.erp.request.created.v1",
        "uz.railtech.erp.quote.ready_for_approval.v1",
    }


def test_platform_bff_subscription_b5() -> None:
    """BFF Платформы (B5): события ERP, лидов CRM и сотрудников; адрес — внутри сети compose."""
    bff = {s["name"]: s for s in SUBSCRIPTIONS["subscribers"]}["platform-bff"]
    assert bff["endpoint"] == "http://platform-bff:8000/bus/v1/events"
    assert bff["endpoint_env"] == "RT_BUS_ENDPOINT_PLATFORM_BFF"
    gets = {t.name for t in TYPES if any(fnmatch.fnmatchcase(t.name, m) for m in bff["types"])}
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.erp.")} <= gets
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.crm.lead.")} <= gets
    assert {t.name for t in TYPES if t.name.startswith("uz.railtech.identity.user.")} <= gets
    assert {t.name for t in TYPES if t.domain == "eds"} <= gets, "волна 12: события EDS — колокольчик и счётчики"
    assert not {n for n in gets if n.startswith(("uz.railtech.crm.client.", "uz.railtech.crm.contact."))}


def test_lead_message_added_goes_only_to_platform_bff_and_carries_no_text() -> None:
    """D1-1: сигнал «новое сообщение в переписке лида» — только BFF Платформы (подсказка SSE);
    ERP и EDS его не получают. Текста, вложений и контактов в событии нет: переписку подписчик
    читает API CRM с правами сотрудника."""
    name = "uz.railtech.crm.lead.message_added.v1"
    receivers = {s["name"] for s in SUBSCRIPTIONS["subscribers"] if name in _gets(s)}
    assert receivers == {"platform-bff"}
    t = next(t for t in TYPES if t.name == name)
    props = set(load_json(t.path)["properties"])
    assert not props & {"text", "attachments", "phone", "email", "display_name", "lead"}


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
