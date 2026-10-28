"""Контракт документов: схема тела и каталог переменных из packages/contracts/documents (ADR-0020).

Каталог контракта: параметр → `RT_DOCS_CONTRACTS_DIR` → поиск `packages/contracts/documents` вверх от пакета
(как у rt_bus).
В образе сервиса контракт приходит контекстом сборки `contracts` (D-DOC2, D-DOC3), пакет его не копирует: правда одна.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .errors import BodyError, ContractsNotFoundError
from .model import Lang

CONTRACTS_DIR_ENV = "RT_DOCS_CONTRACTS_DIR"
BODY_SCHEMA = "body.schema.json"
CATALOG_FILE = "variables.yaml"


def contracts_dir(value: str | Path | None = None) -> Path:
    """Каталог `documents` контракта: параметр → `RT_DOCS_CONTRACTS_DIR` → поиск вверх от пакета."""
    raw = value if value is not None else os.environ.get(CONTRACTS_DIR_ENV)
    if raw:
        path = Path(raw)
        if (path / BODY_SCHEMA).is_file():
            return path
        raise ContractsNotFoundError(f"{BODY_SCHEMA} not found in {path} (parameter or {CONTRACTS_DIR_ENV})")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "contracts" / "documents"
        if (candidate / BODY_SCHEMA).is_file():
            return candidate
    raise ContractsNotFoundError(f"packages/contracts/documents not found; set {CONTRACTS_DIR_ENV}")


@lru_cache(maxsize=8)
def _validator(directory: Path) -> Draft202012Validator:
    schema = json.loads((directory / BODY_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


#: Решения архитектора по ревью #295: вложенность узлов, строки таблицы и размер тела ограничены до хранения в базах.
MAX_DEPTH = 20  # уровней вложенности узлов (doc → список → пункт → … → текст)
MAX_TABLE_ROWS = 500  # строк в одной таблице (= maxItems в body.schema.json; счёт на сотни позиций)
MAX_BODY_BYTES = 1_000_000  # сериализованный JSON (UTF-8)
_JSON_DEPTH = (
    3 * MAX_DEPTH + 10
)  # уровней JSON (узел, его content и attrs) — до json.dumps и jsonschema, без RecursionError
_BREAKS = re.compile(r"\r\n|[\r\x0b\x0c]")  # CR LF, CR, VT (ручной перенос Word), FF → \n
_NONCHARACTERS = "\ufdd0-\ufdef\ufffe\uffff" + "".join(
    f"{chr(plane * 0x10000 + 0xFFFE)}{chr(plane * 0x10000 + 0xFFFF)}" for plane in range(1, 17)
)
#: Удаляются: C0 (кроме \t, \n), одиночные суррогаты, нехарактеры Юникода (XML/DOCX их не принимает).
_FORBIDDEN = re.compile(f"[\x00-\x08\x0e-\x1f\ud800-\udfff{_NONCHARACTERS}]")
_BLOCK_CODE = re.compile(r"^doc\.[a-z][a-z0-9_]*$")


def clean_text(text: str) -> str:
    """Нормализация текста на входе: CR LF, CR, VT, FF → перевод строки; прочие C0 (кроме \\t), одиночные суррогаты и
    нехарактеры (U+FDD0–U+FDEF, U+xFFFE/U+xFFFF) вычищаются. Схема тела этих символов не допускает."""
    return _FORBIDDEN.sub("", _BREAKS.sub("\n", text))


def _cleaned(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, Mapping):
        return {clean_text(str(k)): _cleaned(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_cleaned(v) for v in value]
    return value


def _check_depth(value: Any, where: str) -> None:
    """Глубина — итеративно, до любой рекурсии (чистка, json.dumps, jsonschema)."""
    stack: list[tuple[Any, int, int]] = [(value, 1, 1)]
    while stack:
        item, json_depth, node_depth = stack.pop()
        if json_depth > _JSON_DEPTH or node_depth > MAX_DEPTH:
            raise BodyError([f"{where}: nesting depth exceeds {MAX_DEPTH} nodes"])
        if isinstance(item, Mapping):
            children = list(item.values())
            next_node = node_depth + (1 if "type" in item else 0)
        elif isinstance(item, list | tuple):
            children = list(item)
            next_node = node_depth
        else:
            continue
        stack.extend((child, json_depth + 1, next_node) for child in children)


def _check_size(value: Any, where: str) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False).encode())
    except (TypeError, ValueError) as error:
        raise BodyError([f"{where}: not JSON ({error})"]) from error
    if size > MAX_BODY_BYTES:
        raise BodyError([f"{where}: {size} bytes, more than 1 MB ({MAX_BODY_BYTES} bytes)"])


def normalize_body(body: Any) -> dict[str, Any]:
    """Копия тела без управляющих символов (кроме \\t и \\n) — нормализация входа перед проверкой и хранением."""
    if not isinstance(body, Mapping):
        raise BodyError(["#: body must be a JSON object"])
    _check_depth(body, "#")
    cleaned: dict[str, Any] = _cleaned(body)
    _check_size(cleaned, "#")
    return cleaned


def normalize_blocks(blocks: Any) -> dict[str, list[Any]]:
    if not isinstance(blocks, Mapping):
        raise BodyError(["blocks: must be an object {code: [nodes]}"])
    _check_depth(blocks, "blocks")
    cleaned: dict[str, list[Any]] = _cleaned(blocks)
    _check_size(cleaned, "blocks")
    return cleaned


def validate_body(body: Any, directory: str | Path | None = None) -> None:
    """Тело документа по схеме контракта и лимитам; все нарушения — одним `BodyError` (путь → сообщение)."""
    if not isinstance(body, Mapping):
        raise BodyError(["#: body must be a JSON object"])
    _check_depth(body, "#")
    _check_size(body, "#")
    validator = _validator(contracts_dir(directory))
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if errors:
        raise BodyError([f"{'/'.join(str(p) for p in e.absolute_path) or '#'}: {_short(e.message)}" for e in errors])


def validate_blocks(blocks: Any, directory: str | Path | None = None) -> None:
    """Данные блоков с замком: код по каталогу `doc.*`, узлы — те же блочные узлы тела (`#/$defs/block`).

    Служебных узлов рендера (`_block` и т. п.) и чего-либо вне контракта во входных данных быть не может.
    """
    if not isinstance(blocks, Mapping):
        raise BodyError(["blocks: must be an object {code: [nodes]}"])
    _check_depth(blocks, "blocks")
    _check_size(blocks, "blocks")
    validator = _validator(contracts_dir(directory))
    problems: list[str] = []
    for code, nodes in blocks.items():
        label = code if isinstance(code, str) and _BLOCK_CODE.match(code) and len(code) <= 64 else None
        if label is None:
            problems.append(f"blocks: block code {str(code)[:40]!r} is not doc.<code>")
            continue
        if not isinstance(nodes, list):
            problems.append(f"blocks/{label}: must be a list of block nodes")
            continue
        wrapper = {"version": 1, "lang": "ru", "doc": {"type": "doc", "content": nodes}}
        for e in sorted(validator.iter_errors(wrapper), key=lambda e: list(e.absolute_path)):
            path = "/".join(str(p) for p in list(e.absolute_path)[2:])
            problems.append(f"blocks/{label}/{path}: {_short(e.message)}")
    if problems:
        raise BodyError(problems)


def _short(message: str) -> str:
    return message if len(message) <= 200 else message[:197] + "…"


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    type: str
    labels: Mapping[str, str]
    kinds: tuple[str, ...] = ()
    required_for: tuple[str, ...] = ()
    keep_with_previous: bool = False

    def label(self, lang: Lang) -> str:
        return self.labels.get(lang) or self.labels.get("ru") or self.code


@dataclass(frozen=True)
class Catalog:
    """Каталог видов, переменных и блоков (`variables.yaml`)."""

    variables: Mapping[str, CatalogEntry]
    blocks: Mapping[str, CatalogEntry]
    kinds: Mapping[str, Mapping[str, Any]]

    def label(self, code: str, lang: Lang) -> str:
        entry = self.variables.get(code) or self.blocks.get(code)
        return entry.label(lang) if entry else code

    def required_blocks(self, kind: str) -> tuple[str, ...]:
        return tuple(code for code, entry in self.blocks.items() if kind in entry.required_for)

    @classmethod
    def empty(cls) -> Catalog:
        return cls(variables={}, blocks={}, kinds={})


@lru_cache(maxsize=8)
def _catalog(directory: Path) -> Catalog:
    raw = yaml.safe_load((directory / CATALOG_FILE).read_text(encoding="utf-8"))
    variables = {
        v["code"]: CatalogEntry(code=v["code"], type=v["type"], labels=v["label"], kinds=tuple(v.get("kinds", ())))
        for v in raw["variables"]
    }
    blocks = {
        b["code"]: CatalogEntry(
            code=b["code"],
            type="block",
            labels=b["label"],
            required_for=tuple(b.get("required_for", ())),
            keep_with_previous=bool(b.get("keep_with_previous", False)),
        )
        for b in raw["blocks"]
    }
    return Catalog(variables=variables, blocks=blocks, kinds=raw["kinds"])


def load_catalog(directory: str | Path | None = None) -> Catalog:
    return _catalog(contracts_dir(directory))
