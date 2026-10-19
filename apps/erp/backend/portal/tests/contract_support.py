"""Опора сторожа контракта портала (FIX-21): загрузка `erp-portal.yaml`, раскрытие `$ref`, проверка ответа.

Один источник правды о форме ответов — `packages/contracts/openapi/erp-portal.yaml`. Здесь нет ни одного
скопированного списка полей: схема читается из контракта на каждом прогоне. Контракта нет на диске — это
ПАДЕНИЕ теста с понятным сообщением, не пропуск (иначе сторож молча выключился бы в чужом окружении).
"""

from __future__ import annotations

import datetime
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

CONTRACT_RELATIVE = Path("packages") / "contracts" / "openapi" / "erp-portal.yaml"

MOUNT_HINT = (
    "Контракт packages/contracts/openapi/erp-portal.yaml не найден ни в одном родительском каталоге теста. "
    "Бэкенд-тесты ERP идут в контейнере (apps/erp/scripts/test_backend_local.sh): он обязан монтировать "
    "packages/contracts в /packages/contracts. Сторож контракта не пропускается — без контракта он ничего не проверяет."
)


def find_contract_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / CONTRACT_RELATIVE
        if candidate.exists():
            return candidate
    pytest.fail(MOUNT_HINT, pytrace=False)


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return yaml.safe_load(find_contract_path().read_text(encoding="utf-8"))


def resolve_pointer(contract: dict, ref: str):
    assert ref.startswith("#/"), f"поддерживаются только локальные $ref, получено {ref!r}"
    node = contract
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def deref(node, contract: dict | None = None, _depth: int = 0):
    """Схема с раскрытыми `$ref` (циклов в контракте нет; глубина ограничена на случай, если появятся)."""
    contract = contract or load_contract()
    assert _depth < 40, "слишком глубокая вложенность $ref — цикл в контракте?"
    if isinstance(node, dict):
        if "$ref" in node:
            return deref(resolve_pointer(contract, node["$ref"]), contract, _depth + 1)
        return {key: deref(value, contract, _depth + 1) for key, value in node.items()}
    if isinstance(node, list):
        return [deref(item, contract, _depth + 1) for item in node]
    return node


def component(name: str) -> dict:
    return deref(load_contract()["components"]["schemas"][name])


def error_codes() -> list[str]:
    return list(load_contract()["components"]["schemas"]["ErrorCode"]["enum"])


# ── Форматы: проверяем сами, чтобы не зависеть от необязательных библиотек jsonschema ─────────────────

format_checker = FormatChecker(formats=())


@format_checker.checks("date", raises=ValueError)
def _is_date(value) -> bool:
    if not isinstance(value, str):
        return True
    datetime.date.fromisoformat(value)
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


@format_checker.checks("date-time", raises=ValueError)
def _is_datetime(value) -> bool:
    if not isinstance(value, str):
        return True
    parsed = datetime.datetime.fromisoformat(value)
    return parsed.tzinfo is not None  # RFC 3339: часовой пояс обязателен


@format_checker.checks("uri")
def _is_uri(value) -> bool:
    if not isinstance(value, str):
        return True
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@format_checker.checks("email")
def _is_email(value) -> bool:
    if not isinstance(value, str):
        return True
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def schema_errors(instance, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=format_checker)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<корень>'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
    ]


def _merged_properties(schema: dict) -> dict | None:
    """`properties` схемы вместе с членами `allOf` (Quote = QuoteListItem + свои поля); `None` — не объект."""
    merged: dict | None = None
    own = schema.get("properties")
    if isinstance(own, dict):
        merged = dict(own)
    for part in schema.get("allOf", []):
        inner = _merged_properties(part)
        if inner is not None:
            merged = {**(merged or {}), **inner}
    return merged


def extra_keys(instance, schema: dict, path: str = "") -> list[str]:
    """Ключи ответа, которых нет в `properties` схемы, на любой глубине.

    Контракт без `additionalProperties: false` не значит «можно лишнее»: клиент строится по схеме, а лишние поля —
    это утечка внутреннего слоя (себестоимость, ставка НДС, внутренние id).
    """
    problems: list[str] = []
    branches = schema.get("oneOf") or schema.get("anyOf")
    if branches:
        for branch in branches:
            if not schema_errors(instance, branch):
                return extra_keys(instance, branch, path)
        return problems  # ни одна ветка не подошла — это уже ошибка схемы, её сообщит schema_errors
    if isinstance(instance, dict):
        properties = _merged_properties(schema)
        if properties is None:
            return problems
        for key in instance:
            if key not in properties:
                problems.append(f"{path or '<корень>'}: лишний ключ {key!r} (нет в схеме контракта)")
        for key, value in instance.items():
            if key in properties:
                problems.extend(extra_keys(value, properties[key], f"{path}/{key}"))
    elif isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(instance):
            problems.extend(extra_keys(item, schema["items"], f"{path}[{index}]"))
    return problems


def required_missing(instance, schema: dict, path: str = "") -> list[str]:
    """«Ни меньше»: все `required` схемы присутствуют (jsonschema это тоже проверяет; здесь — читаемое сообщение)."""
    return [m for m in schema_errors(instance, schema) if "is a required property" in m]


def check_response(instance, schema: dict) -> list[str]:
    """Все нарушения формы: типы, форматы, `required` и лишние ключи."""
    return schema_errors(instance, schema) + extra_keys(instance, schema)


def response_schema(path: str, method: str, status: str = "200") -> dict:
    operation = load_contract()["paths"][path][method]
    return deref(operation["responses"][status]["content"]["application/json"]["schema"])


def contract_get_paths() -> set[str]:
    return {path for path, item in load_contract()["paths"].items() if "get" in item}


def contract_post_paths() -> set[str]:
    return {path for path, item in load_contract()["paths"].items() if "post" in item}
