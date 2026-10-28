"""Контракт документов (ADR-0020): схема тела, примеры, каталог переменных, совместимость (documents_compat)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
import yaml
from contracts_events import CONTRACTS
from documents_compat import BODY, CATALOG, check, semver, working_tree
from jsonschema import Draft202012Validator

DOCS = CONTRACTS / "documents"
SCHEMA: dict[str, Any] = json.loads((DOCS / "body.schema.json").read_text(encoding="utf-8"))
CATALOG_DATA: dict[str, Any] = yaml.safe_load((DOCS / "variables.yaml").read_text(encoding="utf-8"))
EXAMPLES = sorted((DOCS / "examples").glob("*.json"))
VALIDATOR = Draft202012Validator(SCHEMA)


def walk(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            out += walk(value)
    elif isinstance(node, list):
        for value in node:
            out += walk(value)
    return out


def test_schema_is_valid_and_versioned() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert semver(SCHEMA) is not None
    assert SCHEMA["properties"]["version"] == {"const": 1, "description": "Мажор формата тела"}


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid_and_use_catalog_codes(path: Any) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    VALIDATOR.validate(body)
    variables = {v["code"] for v in CATALOG_DATA["variables"]}
    blocks = {b["code"] for b in CATALOG_DATA["blocks"]}
    for node in walk(body):
        if node.get("type") == "variable":
            assert node["attrs"]["code"] in variables
        if node.get("type") == "block":
            assert node["attrs"]["code"] in blocks
        if "var" in node and len(node) == 1:
            assert node["var"] in variables


def test_examples_cover_letter_contract_invoice_and_uzbek() -> None:
    names = {p.stem for p in EXAMPLES}
    assert names >= {"letter", "letter.uz", "contract", "invoice"}
    invoice = json.loads((DOCS / "examples" / "invoice.json").read_text(encoding="utf-8"))
    assert any(n.get("type") == "table" for n in walk(invoice)), "счёт — с таблицей позиций"


@pytest.mark.parametrize(
    "node",
    [
        {"type": "paragraph", "content": [{"type": "text", "text": "<b>x</b>", "marks": [{"type": "textStyle"}]}]},
        {"type": "paragraph", "attrs": {"class": "red"}},
        {"type": "image", "attrs": {"src": "file:///etc/passwd"}},
        {"type": "paragraph", "content": [{"type": "variable", "attrs": {"code": "{{company.name}}"}}]},
        {"type": "heading", "attrs": {"level": 4}},
    ],
)
def test_schema_rejects_unknown_nodes_styles_and_bad_codes(node: dict[str, Any]) -> None:
    body = {"version": 1, "lang": "ru", "doc": {"type": "doc", "content": [node]}}
    assert list(VALIDATOR.iter_errors(body))


def test_catalog_codes_are_unique_and_labels_follow_language_rules() -> None:
    for section in ("variables", "blocks"):
        codes = [v["code"] for v in CATALOG_DATA[section]]
        assert len(codes) == len(set(codes)), section
    labels = [v["label"] for section in ("variables", "blocks") for v in CATALOG_DATA[section]]
    labels += [k["label"] for k in CATALOG_DATA["kinds"].values()]
    for label in labels:
        assert not re.search(r"[А-Яа-яЁёЎўҚқҒғҲҳ]", label["uz"]), f"uz — латиница: {label['uz']}"
        assert not re.search(r"[oOgG]['‘’`]", label["uz"]), f"oʻ и gʻ — только U+02BB: {label['uz']}"
        assert re.search(r"[А-Яа-яЁё]", label["ru"]), label["ru"]


def test_required_blocks_of_legal_kinds_match_erp() -> None:
    """Те же обязательные блоки, что REQUIRED_TEMPLATE_BLOCKS ERP (crm/services/document_blocks.py)."""
    required: dict[str, set[str]] = {}
    for block in CATALOG_DATA["blocks"]:
        for kind in block.get("required_for", ()):
            required.setdefault(kind, set()).add(block["code"])
    assert required["invoice"] >= {"doc.items_table", "doc.totals", "doc.payment_requisites"}
    assert required["act"] >= {"doc.items_table", "doc.totals", "doc.signatures"}
    assert required["contract"] >= {"doc.spec_table", "doc.totals", "doc.requisites_and_signatures"}


# ─── совместимость (documents_compat) ─────────────────────────────────────────────────────────────


def tree(schema: dict[str, Any] | None = None, **files: Any) -> dict[str, str]:
    out = working_tree()
    if schema is not None:
        out[BODY] = json.dumps(schema, ensure_ascii=False)
    for path, content in files.items():
        out[path.replace("__", "/").replace("_dot_", ".")] = content
    return out


def bumped(schema: dict[str, Any], version: str) -> dict[str, Any]:
    new = copy.deepcopy(schema)
    new["$comment"] = re.sub(r"semver \d+\.\d+\.\d+", f"semver {version}", new["$comment"])
    return new


def test_unchanged_contract_is_compatible() -> None:
    assert check(working_tree(), working_tree()) == []


def test_new_node_type_with_minor_bump_is_compatible() -> None:
    new = bumped(SCHEMA, "1.1.0")
    new["$defs"]["block"]["oneOf"].append({"$ref": "#/$defs/hardBreak"})
    assert check(working_tree(), tree(new)) == []


def test_change_without_version_bump_is_breaking() -> None:
    new = copy.deepcopy(SCHEMA)
    new["$defs"]["block"]["oneOf"].append({"$ref": "#/$defs/hardBreak"})
    assert any("поднимите минор" in p for p in check(working_tree(), tree(new)))


def test_narrowing_that_breaks_a_stored_example_is_breaking() -> None:
    new = bumped(SCHEMA, "1.1.0")
    new["$defs"]["block"]["oneOf"] = [r for r in new["$defs"]["block"]["oneOf"] if r["$ref"] != "#/$defs/signature"]
    problems = check(working_tree(), tree(new))
    assert any("(база) не проходит новую схему" in p for p in problems)


def test_major_change_and_removed_codes_are_breaking() -> None:
    new = bumped(SCHEMA, "1.1.0")
    new["properties"]["version"] = {"const": 2}
    catalog = copy.deepcopy(CATALOG_DATA)
    catalog["variables"] = [v for v in catalog["variables"] if v["code"] != "company.inn"]
    head = tree(new)
    head[CATALOG] = yaml.safe_dump(catalog, allow_unicode=True)
    problems = check(working_tree(), head)
    assert any("сменён мажор" in p for p in problems)
    assert any("company.inn" in p for p in problems)


def test_new_files_are_not_breaking() -> None:
    assert check({}, working_tree()) == []


# ─── kitchen-sink: каждый узел, атрибут и значение перечисления есть в примерах ─────────────────────────


def _resolve(node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node and node["$ref"].startswith("#/"):
        target: Any = SCHEMA
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _enums(schema: Any, name: str | None, out: dict[str, set[Any]], seen: set[int]) -> None:
    schema = _resolve(schema)
    if not isinstance(schema, dict) or id(schema) in seen:
        return
    seen.add(id(schema))
    if "enum" in schema and name:
        out.setdefault(name, set()).update(schema["enum"])
    for key, sub in (schema.get("properties") or {}).items():
        _enums(sub, key, out, seen)
    for key in ("items", "additionalProperties"):
        _enums(schema.get(key), name, out, seen)
    for key in ("oneOf", "anyOf", "allOf"):
        for sub in schema.get(key) or ():
            _enums(sub, name, out, seen)


def test_kitchen_sink_covers_every_node_attribute_and_enum_value() -> None:
    """Иначе documents_compat не заметит ужесточение: проверка совместимости опирается на корпус примеров."""
    sink = json.loads((DOCS / "examples" / "kitchen-sink.json").read_text(encoding="utf-8"))
    nodes = walk(sink)
    for name, definition in SCHEMA["$defs"].items():
        const = ((definition.get("properties") or {}).get("type") or {}).get("const")
        if const is None or const == "doc":
            continue
        of_type = [n for n in nodes if n.get("type") == const]
        assert of_type, f"нет узла {const} ({name})"
        attrs = _resolve((definition.get("properties") or {}).get("attrs") or {})
        for attr in attrs.get("properties") or {}:
            assert any(attr in (n.get("attrs") or {}) for n in of_type), f"{const}.attrs.{attr}"
    enums: dict[str, set[Any]] = {}
    _enums(SCHEMA, None, enums, set())
    corpus = [n for path in EXAMPLES for n in walk(json.loads(path.read_text(encoding="utf-8")))]
    for prop, values in enums.items():
        used = {n[prop] for n in corpus if prop in n and not isinstance(n[prop], dict | list)}
        assert values <= used, f"{prop}: нет значений {sorted(map(str, values - used))}"
    for key in ("lineHeight", "marginDeltaMm", "leadMm", "orientation", "density"):
        assert any(key in n for n in nodes), key
