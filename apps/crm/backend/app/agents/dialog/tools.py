"""Инструменты диалогового агента и их выполнение (SPEC §7.1).

Модель получает настоящий результат вызова: успех, номер запроса или ошибку. Подставной
`{"ok": true}` приводил к «передал менеджеру», когда ничего не произошло (аудит 2026-10-12).
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from app.agents.llm import ChatResult
from app.agents.mcp_client import ToolCaller

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

FAILED: Final = {"ok": False, "error": "failed", "note": "Действие не выполнено."}
NOT_ALLOWED: Final = {"ok": False, "error": "not_allowed", "note": "Инструмент недоступен."}


@dataclass(slots=True)
class ToolOutcome:
    callback: bool = False
    service: bool = False
    request_number: int | None = None
    failed: bool = False
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)


async def run_tools(
    tools: ToolCaller,
    result: ChatResult,
    allowed_tools: list[dict[str, Any]],
    token: str,
    lead_id: int,
    timeout_s: float,
) -> ToolOutcome:
    """Выполнить вызовы модели через crm-mcp; результат каждого — для ответа модели."""
    outcome = ToolOutcome()
    allowed = {t["function"]["name"] for t in allowed_tools}
    for call in result.tool_calls:
        if call.name not in allowed:
            outcome.outputs[call.id] = NOT_ALLOWED
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
        {"role": "tool", "tool_call_id": c.id, "content": _json(outputs.get(c.id, FAILED))}
        for c in result.tool_calls
    ]
    return [assistant, *replies]


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
