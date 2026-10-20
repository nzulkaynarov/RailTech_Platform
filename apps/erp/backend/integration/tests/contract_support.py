"""Опора сторожа контракта шва CRM ↔ ERP (FIX-30): `erp-integration.yaml`.

Загрузка, раскрытие `$ref` и все проверки — общие с сторожем портала (`core/tests/openapi_contract.py`); здесь только
привязка к файлу контракта integration. Проверки не ослаблены: типы, форматы, `required` и лишние ключи.
"""

from __future__ import annotations

from core.tests.openapi_contract import OpenApiContract, check_response, extra_keys, schema_errors  # noqa: F401

CONTRACT_FILE = "erp-integration.yaml"

integration_contract = OpenApiContract(CONTRACT_FILE)

#: Префикс ресурсов integration (`servers` контракта).
PREFIX = "/api/integration/v1"


def component(name: str) -> dict:
    return integration_contract.component(name)


def response_schema(path: str, method: str = "get", status: str = "200") -> dict:
    return integration_contract.response_schema(path, method, status)


def contract_get_paths() -> set[str]:
    return integration_contract.get_paths()


def enum_values(name: str) -> list[str]:
    """Значения enum-схемы контракта (`DealStage`, `InvoiceStatus` …) — единственный источник «что достижимо»."""
    return list(component(name)["enum"])


def contract_operations() -> dict[tuple[str, str], set[str]]:
    """(МЕТОД, путь) → коды ответов, объявленные контрактом, по всем операциям `erp-integration.yaml`."""
    return integration_contract.operations()
