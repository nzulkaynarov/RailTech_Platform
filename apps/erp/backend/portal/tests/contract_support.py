"""Опора сторожа контракта портала (FIX-21): `erp-portal.yaml`.

Загрузка, раскрытие `$ref` и все проверки живут в одном месте — `core/tests/openapi_contract.py` (FIX-30: тот же
код проверяет `erp-integration.yaml`). Здесь — только привязка к файлу портала и прежние имена, чтобы тесты портала
не менялись; проверки не ослаблены.
"""

from __future__ import annotations

from pathlib import Path

from core.tests.openapi_contract import (  # noqa: F401  (имена — публичный интерфейс для тестов портала)
    CONTRACTS_RELATIVE,
    MOUNT_HINT,
    OpenApiContract,
    check_response,
)
from core.tests.openapi_contract import deref as _deref
from core.tests.openapi_contract import (  # noqa: F401  (имена — публичный интерфейс для тестов портала)
    extra_keys,
    format_checker,
    required_missing,
    resolve_pointer,
    schema_errors,
)

CONTRACT_FILE = "erp-portal.yaml"
CONTRACT_RELATIVE = CONTRACTS_RELATIVE / CONTRACT_FILE

_portal = OpenApiContract(CONTRACT_FILE)


def find_contract_path() -> Path:
    return _portal.find_path()


def load_contract() -> dict:
    return _portal.load()


def deref(node, contract: dict | None = None, _depth: int = 0):
    return _deref(node, contract or load_contract(), _depth)


def component(name: str) -> dict:
    return _portal.component(name)


def error_codes() -> list[str]:
    return list(load_contract()["components"]["schemas"]["ErrorCode"]["enum"])


def response_schema(path: str, method: str, status: str = "200") -> dict:
    return _portal.response_schema(path, method, status)


def contract_get_paths() -> set[str]:
    return _portal.get_paths()


def contract_post_paths() -> set[str]:
    return _portal.post_paths()
