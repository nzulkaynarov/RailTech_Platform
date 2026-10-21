"""Инструменты диалогового агента и их выполнение (SPEC §7.1).

Модель получает настоящий результат вызова: успех, номер запроса или ошибку. Подставной
`{"ok": true}` приводил к «передал менеджеру», когда ничего не произошло (аудит 2026-10-12).
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from app.agents.dialog import erp_tools
from app.agents.erp_mcp import ErpToolCaller
from app.agents.llm import ChatResult, ToolCall
from app.agents.mcp_client import ToolCaller
from app.security.erp_agent_context import ErpScope

logger = structlog.get_logger(__name__)

TOOLS: Final[list[dict[str, Any]]] = [
    {
        "type": "function",
        "function": {
            "name": "request_callback",
            "description": (
                "Клиент сам попросил, чтобы с ним связались. "
                "Укажи удобное время, если он его назвал."
            ),
            "parameters": {
                "type": "object",
                "properties": {"preferred_time": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_qualification",
            "description": "Записать сведения, которые клиент сам сообщил о себе и задаче.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "company_size": {"type": "string"},
                            "region": {"type": "string"},
                            "timeline": {"type": "string", "enum": ["<1m", "<3m", "<12m", ">12m"]},
                            "decision_role": {
                                "type": "string",
                                "enum": ["decision_maker", "influencer", "researcher"],
                            },
                            "budget_hint": {"type": "string"},
                        },
                        "additionalProperties": False,
                    }
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        },
    },
]

# Не больше стольких вызовов инструментов за раунд: остальные модель получает отказанными.
MAX_CALLS_PER_ROUND: Final = 5
TOO_MANY: Final = {"ok": False, "error": "too_many_calls", "note": "Слишком много вызовов сразу."}
FAILED: Final = {"ok": False, "error": "failed", "note": "Действие не выполнено."}
NOT_ALLOWED: Final = {"ok": False, "error": "not_allowed", "note": "Инструмент недоступен."}


@dataclass(slots=True)
class ToolOutcome:
    callback: bool = False
    service: bool = False
    request_number: int | None = None
    failed: bool = False
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Сервисный режим (M3-CRM-07): были ли вызовы ERP, отказал ли хоть один, и их результаты как
    # источник чисел для проверки ответа (`erp_tools.facts_of`).
    erp_called: bool = False
    erp_failed: bool = False
    # Отказ ERP, после которого нужен запрос менеджеру: не `invalid_arguments` (это ошибка модели).
    erp_handover: bool = False
    erp_facts: list[str] = field(default_factory=list)


async def run_tools(
    tools: ToolCaller,
    result: ChatResult,
    allowed_tools: list[dict[str, Any]],
    token: str,
    lead_id: int,
    timeout_s: float,
    outcome: ToolOutcome | None = None,
    erp: ErpToolCaller | None = None,
    erp_scope: ErpScope | None = None,
) -> ToolOutcome:
    """Выполнить вызовы модели: crm-mcp и (в сервисном режиме) erp-mcp; результаты — модели."""
    outcome = outcome or ToolOutcome()
    allowed = {t["function"]["name"] for t in allowed_tools}
    for index, call in enumerate(result.tool_calls):
        if index >= MAX_CALLS_PER_ROUND:
            outcome.outputs[call.id] = TOO_MANY
            continue
        if call.name not in allowed:
            outcome.outputs[call.id] = NOT_ALLOWED
            continue
        if call.name in erp_tools.ERP_TOOL_NAMES:
            if erp is None or erp_scope is None:
                outcome.outputs[call.id] = NOT_ALLOWED
                continue
            output, failure = await erp_tools.run_erp_call(erp, erp_scope, call)
            outcome.outputs[call.id] = output
            outcome.erp_called = True
            outcome.erp_failed = outcome.erp_failed or failure is not None
            outcome.erp_handover = outcome.erp_handover or failure not in (
                None,
                "invalid_arguments",
            )
            outcome.erp_facts.append(erp_tools.facts_of(output))
            continue
        try:
            raw = await asyncio.wait_for(
                tools.call("crm", call.name, call.arguments, token), timeout_s
            )
        except Exception:  # noqa: BLE001 — модель узнает о сбое и не пообещает лишнего
            logger.warning("dialog_tool_failed", tool=call.name, lead_id=lead_id)
            outcome.outputs[call.id] = FAILED
            outcome.failed = True
            continue
        data = raw if isinstance(raw, dict) else {"ok": True}
        outcome.callback = outcome.callback or call.name == "request_callback"
        if call.name == "create_service_request":
            outcome.service = True
            number = data.get("service_request_id")
            outcome.request_number = number if isinstance(number, int) else None
            data = {"ok": True, "request_number": outcome.request_number}
        outcome.outputs[call.id] = data
    return outcome


def tool_messages(result: ChatResult, outputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    assistant = {
        "role": "assistant",
        "content": result.text or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": _json(c.arguments)},
            }
            for c in result.tool_calls
        ],
    }
    replies = [
        {"role": "tool", "tool_call_id": c.id, "content": _content(c, outputs.get(c.id, FAILED))}
        for c in result.tool_calls
    ]
    return [assistant, *replies]


def _content(call: ToolCall, output: dict[str, Any]) -> str:
    """Данные ERP — в блоке `<erp_data>` («данные, не инструкции»), остальное — JSON как раньше."""
    if (
        call.name in erp_tools.ERP_TOOL_NAMES
        and output is not NOT_ALLOWED
        and output is not TOO_MANY
    ):
        return erp_tools.wrapped(output)
    return _json(output)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
