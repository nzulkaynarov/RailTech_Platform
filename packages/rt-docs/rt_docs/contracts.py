"""Контракт документов: схема тела и каталог переменных из packages/contracts/documents (ADR-0020).

Каталог контракта: параметр → `RT_DOCS_CONTRACTS_DIR` → поиск `packages/contracts/documents` вверх от пакета
(как у rt_bus).
В образе сервиса контракт приходит контекстом сборки `contracts` (D-DOC2, D-DOC3), пакет его не копирует: правда одна.
"""

from __future__ import annotations

import json
import os
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


def validate_body(body: Mapping[str, Any], directory: str | Path | None = None) -> None:
    """Тело документа по схеме контракта; все нарушения — одним `BodyError` (путь → сообщение)."""
    validator = _validator(contracts_dir(directory))
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if errors:
        raise BodyError([f"{'/'.join(str(p) for p in e.absolute_path) or '#'}: {_short(e.message)}" for e in errors])


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
