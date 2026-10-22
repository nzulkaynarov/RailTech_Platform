"""Правила совместимости L8 (scripts/events_compat.py): фикстуры «было/стало» на каждое правило."""

from __future__ import annotations

import copy
import subprocess
from typing import Any

import events_compat
import pytest
from events_compat import check

TYPE = "events/erp/quote.sent.v1.json"
DEFS = "events/erp/_defs.v1.json"


def schema(**props: Any) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["erp_quote_id"],
        "properties": {"erp_quote_id": {"type": "integer"}, **props},
        "additionalProperties": False,
    }


BASE = schema(
    status={"type": "string", "enum": ["sent", "viewed"]},
    note={"type": "string", "maxLength": 100},
    url={"type": "string", "format": "uri"},
    version={"type": "integer", "minimum": 1},
    amount={"oneOf": [{"type": "string", "pattern": "^\\d+\\.\\d{2}$"}, {"type": "null"}]},
)


def changed(mutate) -> dict[str, Any]:  # noqa: ANN001
    new = copy.deepcopy(BASE)
    mutate(new)
    return new


def run(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[str]:
    base = {TYPE: old} if old is not None else {}
    head = {TYPE: new} if new is not None else {}
    return check(base, head)


# ─── допустимо ────────────────────────────────────────────────────────────────────────────────


def test_unchanged_is_compatible() -> None:
    assert run(BASE, copy.deepcopy(BASE)) == []


def test_new_optional_field_is_compatible() -> None:
    assert run(BASE, changed(lambda s: s["properties"].update(extra={"type": "string"}))) == []


def test_new_type_file_is_compatible() -> None:
    assert run(None, BASE) == []
    assert check({TYPE: BASE}, {TYPE: BASE, "events/erp/quote.sent.v2.json": schema()}) == []


def test_description_and_title_changes_are_compatible() -> None:
    assert run(BASE, changed(lambda s: s.update(title="Новое", description="Другое"))) == []


def test_enum_widening_is_compatible() -> None:
    assert run(BASE, changed(lambda s: s["properties"]["status"]["enum"].append("accepted"))) == []


def test_relaxing_constraints_is_compatible() -> None:
    def relax(s: dict[str, Any]) -> None:
        s["properties"]["note"]["maxLength"] = 200
        s["properties"]["version"].pop("minimum")
        s["properties"]["url"].pop("format")

    assert run(BASE, changed(relax)) == []


def test_type_widening_to_nullable_is_compatible() -> None:
    assert run(BASE, changed(lambda s: s["properties"]["note"].update(type=["string", "null"]))) == []


def test_oneof_new_variant_is_compatible() -> None:
    assert run(BASE, changed(lambda s: s["properties"]["amount"]["oneOf"].append({"type": "integer"}))) == []


def test_additional_properties_relaxed_is_compatible() -> None:
    assert run(BASE, changed(lambda s: s.update(additionalProperties=True))) == []


# ─── ломающее ─────────────────────────────────────────────────────────────────────────────────


def assert_breaking(problems: list[str], fragment: str) -> None:
    assert problems, "ожидалось ломающее изменение"
    assert any(fragment in p for p in problems), problems


def test_removed_field_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"].pop("note"))), "поле удалено")


def test_renamed_field_is_breaking() -> None:
    def rename(s: dict[str, Any]) -> None:
        s["properties"]["comment"] = s["properties"].pop("note")

    assert_breaking(run(BASE, changed(rename)), "/properties/note: поле удалено или переименовано")


def test_type_change_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["note"].update(type="integer"))), "смена типа")


def test_type_narrowing_is_breaking() -> None:
    old = changed(lambda s: s["properties"]["note"].update(type=["string", "null"]))
    assert_breaking(run(old, copy.deepcopy(BASE)), "смена типа")


def test_new_required_field_is_breaking() -> None:
    def add_required(s: dict[str, Any]) -> None:
        s["properties"]["valid_until"] = {"type": "string", "format": "date"}
        s["required"].append("valid_until")

    assert_breaking(run(BASE, changed(add_required)), "новое обязательное поле «valid_until»")


def test_existing_optional_becomes_required_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["required"].append("note"))), "новое обязательное поле «note»")


def test_enum_narrowing_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["status"]["enum"].remove("viewed"))), "сужение enum")


def test_enum_added_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["note"].update(enum=["a"]))), "добавлен enum")


def test_const_change_is_breaking() -> None:
    old = changed(lambda s: s["properties"]["status"].update(const="sent"))
    new = changed(lambda s: s["properties"]["status"].update(const="viewed"))
    assert_breaking(run(old, new), "const")


def test_format_added_or_changed_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["note"].update(format="email"))), "формат")
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["url"].update(format="uri-reference"))), "формат")


def test_pattern_change_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["note"].update(pattern="^[a-z]+$"))), "шаблон")


@pytest.mark.parametrize(
    ("field", "key", "value"),
    [("note", "maxLength", 50), ("note", "minLength", 1), ("version", "minimum", 2), ("version", "maximum", 10)],
)
def test_tightened_bounds_are_breaking(field: str, key: str, value: int) -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"][field].update({key: value}))), key)


def test_additional_properties_tightened_is_breaking() -> None:
    old = changed(lambda s: s.pop("additionalProperties"))
    assert_breaking(run(old, copy.deepcopy(BASE)), "ужесточение additionalProperties")
    old_true = changed(lambda s: s.update(additionalProperties=True))
    assert_breaking(run(old_true, copy.deepcopy(BASE)), "ужесточение additionalProperties")


def test_additional_properties_schema_added_is_breaking() -> None:
    old = changed(lambda s: s.pop("additionalProperties"))
    new = changed(lambda s: s.update(additionalProperties={"type": "string"}))
    assert_breaking(run(old, new), "additionalProperties")


def test_deleted_type_file_is_breaking() -> None:
    assert_breaking(run(BASE, None), "файл удалён")


def test_oneof_variant_removed_is_breaking() -> None:
    assert_breaking(run(BASE, changed(lambda s: s["properties"]["amount"]["oneOf"].pop())), "вариант удалён")


def test_new_condition_is_breaking() -> None:
    cond = {"if": {"properties": {"status": {"const": "viewed"}}}, "then": {"required": ["note"]}}
    assert_breaking(run(BASE, changed(lambda s: s.update(cond))), "условие if")
    assert_breaking(run(BASE, changed(lambda s: s.update(allOf=[{"required": ["note"]}]))), "allOf")


def test_items_tightened_is_breaking() -> None:
    old = changed(lambda s: s["properties"].update(tags={"type": "array", "items": {"type": "string"}}))
    new = changed(lambda s: s["properties"].update(tags={"type": "array", "items": {"type": "string", "maxLength": 3}}))
    assert_breaking(run(old, new), "/properties/tags/items: maxLength")


# ─── $ref и общие определения ─────────────────────────────────────────────────────────────────


def tree_with_defs(payload_def: dict[str, Any], extra_defs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        DEFS: {"$defs": {"QuoteSent": payload_def, **(extra_defs or {})}},
        TYPE: {
            "type": "object",
            "required": ["payload"],
            "properties": {"payload": {"$ref": "_defs.v1.json#/$defs/QuoteSent"}},
            "additionalProperties": False,
        },
    }


def test_change_in_shared_defs_is_seen_through_ref() -> None:
    old = tree_with_defs(schema())
    new = tree_with_defs(changed(lambda s: s["required"].append("note")))
    problems = check(old, new)
    assert any(p.startswith(TYPE) and "/properties/payload" in p for p in problems), problems
    assert any(p.startswith(DEFS) for p in problems), problems


def test_removed_definition_is_breaking() -> None:
    old = tree_with_defs(schema(), {"Unused": {"type": "string"}})
    assert_breaking(check(old, tree_with_defs(schema())), "/$defs/Unused: определение удалено")


def test_ref_to_other_definition_with_same_shape_is_compatible() -> None:
    old = tree_with_defs(schema())
    new = copy.deepcopy(old)
    new[DEFS]["$defs"]["QuoteSentRenamed"] = new[DEFS]["$defs"]["QuoteSent"]
    new[TYPE]["properties"]["payload"]["$ref"] = "_defs.v1.json#/$defs/QuoteSentRenamed"
    assert check(old, new) == []


def test_broken_ref_in_new_tree_fails() -> None:
    new = tree_with_defs(schema())
    new[TYPE]["properties"]["payload"]["$ref"] = "_missing.v1.json#/$defs/QuoteSent"
    with pytest.raises(ValueError, match="_missing"):
        check({}, new)


def test_unknown_keyword_change_is_reported() -> None:
    assert run(BASE, changed(lambda s: s.update({"x-rt-note": 1}))) == [], "x-* — аннотации"
    assert_breaking(run(BASE, changed(lambda s: s.update(dependencies={"note": ["url"]}))), "правило совместимости")


# ─── CLI и git ────────────────────────────────────────────────────────────────────────────────


def test_missing_base_ref_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert events_compat.main(["--base", "refs/heads/no-such-branch-b2"]) == 2
    assert "не найдена" in capsys.readouterr().err


def test_base_ref_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setenv("CONTRACTS_BASE_REF", "some/ref")
    monkeypatch.setattr(events_compat, "git_tree", lambda ref: seen.append(ref) or {})
    assert events_compat.main([]) == 0
    assert seen == ["some/ref"]


def test_breaking_change_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(events_compat, "git_tree", lambda ref: {TYPE: BASE})
    monkeypatch.setattr(events_compat, "working_tree", lambda: {TYPE: changed(lambda s: s["properties"].pop("note"))})
    assert events_compat.main(["--base", "x"]) == 1
    assert "поле удалено" in capsys.readouterr().out


def test_git_tree_reads_committed_schemas() -> None:
    """База читается через git show: HEAD этого репозитория разбирается без ошибок."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    tree = events_compat.git_tree(head)
    assert all(events_compat.is_schema_path(p) for p in tree)
