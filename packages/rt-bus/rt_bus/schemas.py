"""Реестр JSON Schema по каталогу контрактов `packages/contracts/events` (L2, L6, L11).

Каждая схема регистрируется по `$id` (`https://railtech.uz/contracts/events/...`), относительные `$ref`
разрешаются через реестр `referencing`. Каталог `examples/` пропускается. Два режима проверки `data`:

* строгий (издатель) — схема как есть, `additionalProperties: false` действует;
* терпимый (приёмник, L10) — та же схема без `additionalProperties: false` / `unevaluatedProperties: false`: новое
  необязательное поле издателя не ломает старого подписчика, остальные ошибки (тип, обязательное поле, enum) — отказ.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .envelope import parse_type
from .errors import ConfigError, UnknownEventTypeError

CONTRACTS_DIR_ENV = "RT_BUS_CONTRACTS_DIR"
ENVELOPE_FILE = "envelope.v1.json"

#: Ключевые слова, значение которых — словарь «имя → схема».
_SCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
#: Ключевые слова со значениями-данными, а не схемами.
_DATA_KEYWORDS = frozenset({"enum", "const", "default", "examples", "required", "description", "title"})


def discover_contracts_dir(start: Path | None = None) -> Path | None:
    """Ищет `packages/contracts/events` вверх от `start` (по умолчанию — от пакета и от текущего каталога)."""
    starts = [start] if start is not None else [Path(__file__).resolve().parent, Path.cwd()]
    for origin in starts:
        for parent in [origin, *origin.parents]:
            candidate = parent / "packages" / "contracts" / "events"
            if (candidate / ENVELOPE_FILE).is_file():
                return candidate
    return None


def resolve_contracts_dir(value: str | os.PathLike[str] | None = None) -> Path:
    """Каталог схем событий: параметр → `RT_BUS_CONTRACTS_DIR` → поиск `packages/contracts/events` вверх."""
    raw = value if value is not None else os.environ.get(CONTRACTS_DIR_ENV)
    path = Path(raw) if raw else discover_contracts_dir()
    if path is None or not (path / ENVELOPE_FILE).is_file():
        raise ConfigError(
            f"contracts dir with {ENVELOPE_FILE} not found (parameter or {CONTRACTS_DIR_ENV}): {raw or '<auto>'}"
        )
    return path


def _relax(node: Any) -> Any:
    """Копия схемы без `additionalProperties: false` и `unevaluatedProperties: false` на любой глубине."""
    if isinstance(node, list):
        return [_relax(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("additionalProperties", "unevaluatedProperties") and value is False:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: _relax(sub) for name, sub in value.items()}
        elif key in _DATA_KEYWORDS:
            out[key] = copy.deepcopy(value)
        else:
            out[key] = _relax(value)
    return out


def _format_error(error: ValidationError) -> str:
    where = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{where}: {error.message}"


class SchemaRegistry:
    """Схемы конверта и типов событий из каталога `events/` контракта."""

    def __init__(self, events_dir: str | os.PathLike[str] | None = None) -> None:
        self.events_dir = resolve_contracts_dir(events_dir)
        self._by_path: dict[str, dict[str, Any]] = {}
        strict: list[tuple[str, Resource[Any]]] = []
        relaxed: list[tuple[str, Resource[Any]]] = []
        for file in sorted(self.events_dir.rglob("*.json")):
            rel = file.relative_to(self.events_dir)
            if "examples" in rel.parts:
                continue
            try:
                schema = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ConfigError(f"schema {file} is not readable JSON: {exc}") from exc
            if not isinstance(schema, dict):
                raise ConfigError(f"schema {file} is not an object")
            schema_id = schema.get("$id") or file.resolve().as_uri()
            schema.setdefault("$id", schema_id)
            self._by_path[rel.as_posix()] = schema
            strict.append((schema_id, Resource.from_contents(schema, default_specification=DRAFT202012)))
            relaxed_schema = _relax(schema)
            relaxed.append((schema_id, Resource.from_contents(relaxed_schema, default_specification=DRAFT202012)))
            self._by_path["~relaxed/" + rel.as_posix()] = relaxed_schema
        if ENVELOPE_FILE not in self._by_path:
            raise ConfigError(f"{ENVELOPE_FILE} not found in {self.events_dir}")
        self._strict: Registry[Any] = Registry().with_resources(strict)
        self._relaxed: Registry[Any] = Registry().with_resources(relaxed)
        self._validators: dict[tuple[str, bool], Draft202012Validator] = {}

    def _validator(self, rel_path: str, *, tolerant: bool) -> Draft202012Validator:
        key = (rel_path, tolerant)
        validator = self._validators.get(key)
        if validator is None:
            schema = self._by_path[("~relaxed/" if tolerant else "") + rel_path]
            validator = Draft202012Validator(
                schema,
                registry=self._relaxed if tolerant else self._strict,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )
            self._validators[key] = validator
        return validator

    @staticmethod
    def _errors(validator: Draft202012Validator, instance: Any) -> list[str]:
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [_format_error(error) for error in errors]

    @property
    def types(self) -> list[str]:
        """Все типы событий каталога (файлы `<домен>/<сущность>.<действие>.v<N>.json`)."""
        out = []
        for rel in self._by_path:
            if rel.startswith("~relaxed/") or "/" not in rel or rel.rsplit("/", 1)[1].startswith("_"):
                continue
            domain, name = rel.split("/", 1)
            out.append(f"uz.railtech.{domain}.{name.removesuffix('.json')}")
        return sorted(out)

    def has_type(self, event_type: str) -> bool:
        try:
            return parse_type(event_type).schema_path in self._by_path
        except UnknownEventTypeError:
            return False

    def validate_envelope(self, envelope: Any) -> list[str]:
        """Ошибки конверта по `envelope.v1.json` (+ `time` — RFC 3339 с поясом, `dataschema` соответствует `type`)."""
        errors = self._errors(self._validator(ENVELOPE_FILE, tolerant=False), envelope)
        if errors or not isinstance(envelope, Mapping):
            return errors or ["<root>: envelope is not an object"]
        try:
            moment = datetime.fromisoformat(str(envelope["time"]))
            if moment.tzinfo is None:
                errors.append("time: no UTC offset")
        except ValueError:
            errors.append("time: not RFC 3339")
        try:
            expected = parse_type(str(envelope["type"])).dataschema
            if envelope["dataschema"] != expected:
                errors.append(f"dataschema: {envelope['dataschema']!r} does not match type (expected {expected!r})")
        except UnknownEventTypeError as exc:
            errors.append(f"type: {exc}")
        return errors

    def validate_data(self, event_type: str, data: Any, *, tolerant: bool) -> list[str]:
        """Ошибки `data` по схеме типа. Нет схемы — `UnknownEventTypeError`."""
        rel = parse_type(event_type).schema_path
        if rel not in self._by_path:
            raise UnknownEventTypeError(f"no schema for {event_type} in {self.events_dir}")
        return self._errors(self._validator(rel, tolerant=tolerant), data)

    def check_examples(self) -> dict[str, list[str]]:
        """Ошибки примеров `examples/*.json` (конверт и `data` строго) — для тестов сервисов."""
        problems: dict[str, list[str]] = {}
        for file in sorted(self.events_dir.rglob("examples/*.json")):
            envelope = json.loads(file.read_text(encoding="utf-8"))
            errs = self.validate_envelope(envelope)
            if not errs:
                errs = self.validate_data(envelope["type"], envelope["data"], tolerant=False)
            if errs:
                problems[file.relative_to(self.events_dir).as_posix()] = errs
        return problems
