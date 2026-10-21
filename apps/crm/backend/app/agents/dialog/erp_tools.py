"""Инструменты ERP в сервисном режиме бота (M3-CRM-07; CONTRACTS §5, `mcp-tools.json`).

Модель предлагает вызов, выполняет код: идентификаторы клиента и компании в контекст кладёт
`ErpScope` (из БД по проверенной привязке Telegram), аргументы модели фильтруются по схеме
инструмента (придуманный моделью id компании в ERP не уходит), любой отказ ERP превращается в
честный результат `erp_unavailable` без данных — выдумывать модели нечего. Режим всегда
`customer`: лиду `erp-mcp` не открывается, цены он не получает.

Модели не отданы: `get_document_link` (файл клиенту отправляет код через docs-mcp, ссылку модель
не видит) и `create_request` (запрос менеджеру оформляет `create_service_request` CRM — источник
правды о запросах клиента в CRM один).
"""

import asyncio
import json
from typing import Any, Final

import structlog

from app.agents.erp_mcp import ErpMcpError, ErpToolCaller
from app.agents.llm import ToolCall
from app.security.erp_agent_context import ErpScope

logger = structlog.get_logger(__name__)

ERP_CALL_TIMEOUT_S: Final = 30.0
MAX_ITEMS: Final = 20
UNAVAILABLE: Final = {
    "ok": False,
    "error": "erp_unavailable",
    "note": (
        "Данные из системы получить не удалось. Не называй ни чисел, ни дат, ни номеров. "
        "Скажи, что сейчас не можешь это проверить; вопрос менеджеру система оформит сама."
    ),
}


def _deal_id() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["erp_deal_id"],
        "properties": {"erp_deal_id": {"type": "integer"}},
        "additionalProperties": False,
    }


# Схемы аргументов — как в mcp-tools.json (сверяются тестом); описания — для модели.
_SPECS: Final[tuple[tuple[str, str, dict[str, Any]], ...]] = (
    (
        "list_client_deals",
        "Сделки клиента: номер, стадия, сумма, следующий шаг. Нужны, чтобы узнать erp_deal_id.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    (
        "get_deal_status",
        "Стадия сделки, счета, договоры, КП, акты и поставки. Для «где мой счёт» и статуса заказа.",
        _deal_id(),
    ),
    (
        "get_delivery_status",
        "Строки поставки сделки: статус, ожидаемая дата, трек. Для «когда поставка».",
        _deal_id(),
    ),
    (
        "list_client_documents",
        "Список документов клиента (вид, номер, дата). Сам файл отправляет система.",
        {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["quote", "contract", "invoice", "act", "waybill", "receipt", "other"],
                },
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
            },
            "additionalProperties": False,
        },
    ),
    (
        "search_catalog",
        "Каталог: название, единица, цена (или «по запросу»), наличие, срок. «Сколько стоит X».",
        {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "additionalProperties": False,
        },
    ),
)
ERP_TOOLS: Final[list[dict[str, Any]]] = [
    {"type": "function", "function": {"name": n, "description": d, "parameters": p}}
    for n, d, p in _SPECS
]
ERP_TOOL_NAMES: Final = frozenset(n for n, _, _ in _SPECS)
_PROPERTIES: Final = {n: frozenset(p["properties"]) for n, _, p in _SPECS}


def clean_args(tool: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Только аргументы из схемы инструмента: всё остальное (в т.ч. чужие id) отбрасывает код."""
    return {k: v for k, v in raw.items() if k in _PROPERTIES.get(tool, frozenset())}


def _limit(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and len(data) > MAX_ITEMS:
        return {"ok": True, "result": data[:MAX_ITEMS], "truncated": True}
    return {"ok": True, "result": data}


async def run_erp_call(
    erp: ErpToolCaller, scope: ErpScope, call: ToolCall
) -> tuple[dict[str, Any], bool]:
    """Результат для модели и признак отказа. Данные ERP попадают модели только в `result`."""
    args = clean_args(call.name, call.arguments)
    try:
        data = await asyncio.wait_for(erp.call(call.name, args, scope), ERP_CALL_TIMEOUT_S)
    except ErpMcpError as exc:
        logger.warning("erp_tool_failed", tool=call.name, kind=exc.kind, code=exc.code)
        return UNAVAILABLE, True
    except Exception:
        logger.exception("erp_tool_crashed", tool=call.name)
        return UNAVAILABLE, True
    return _limit(data), False


def facts_of(output: dict[str, Any]) -> str:
    """Текст результата инструмента для проверки чисел ответа."""
    return json.dumps(output, ensure_ascii=False, default=str)
