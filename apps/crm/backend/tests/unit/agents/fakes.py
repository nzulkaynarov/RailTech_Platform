"""Подмены MCP и модели для unit-тестов графа (без сети)."""

from collections.abc import Sequence
from typing import Any

from app.agents.llm import ChatResult, ToolCall


class FakeTools:
    def __init__(self, lead: dict[str, Any], kb: dict[str, Any]) -> None:
        self.lead = lead
        self.kb = kb
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        self.calls.append((server, tool, args))
        if tool == "get_lead_context":
            return self.lead
        if tool == "search_kb":
            return self.kb
        return {"ok": True}


class ReplayModel:
    """Отдаёт заранее записанные ответы по порядку и запоминает запросы."""

    def __init__(self, *responses: ChatResult) -> None:
        self.responses = list(responses)
        self.requests: list[Sequence[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        name: str = "llm",
    ) -> ChatResult:
        self.requests.append(messages)
        return self.responses.pop(0)


def reply(text: str, *calls: ToolCall) -> ChatResult:
    return ChatResult(
        text=text,
        model="dialog-model",
        tokens_in=100,
        tokens_out=20,
        latency_ms=900,
        tool_calls=list(calls),
    )


def lead(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "lead_id": 1,
        "display_name": "Азиз",
        "language": "ru",
        "stage": "engaged",
        "score": 0,
        "owner_mode": "bot",
        "need_summary": "касса для магазина",
        "product_interest": [],
        "qualification": {},
        "notes": [],
        "history": [{"role": "lead", "text": "вопрос"}],
        "customer": False,
    }
    base.update(overrides)
    return base


def kb(best: float | None = 0.8) -> dict[str, Any]:
    hits = (
        []
        if best is None
        else [
            {
                "chunk_id": 10,
                "document_title": "RT-POS",
                "product_key": "pos",
                "heading_path": "Тарифы",
                "content": "Тариф Старт включает одну кассу.",
                "similarity": best,
            }
        ]
    )
    return {
        "hits": hits,
        "best_score": best,
        "confident": bool(best and best >= 0.55),
        "language": "ru",
    }
