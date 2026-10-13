"""Режим customer диалогового агента (SPEC §7.1, §7.3, сценарий C5).

Запрос документа разбирает код (`domain/documents.py`), поиск — docs-mcp строго
по клиенту из подписанного контекста. Модель только формулирует ответ.
"""

from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from app.agents import prompts
from app.agents.mcp_client import ToolCaller
from app.domain import documents
from app.schemas.settings import AppSettings

CHOICES_LIMIT: Final = 10
CUSTOMER_TOOLS: Final[list[dict[str, Any]]] = [
    {
        "type": "function",
        "function": {
            "name": "create_service_request",
            "description": (
                "Клиент сообщил о проблеме, спросил статус работ или просит что-то изменить. "
                "Кратко опиши суть запроса."
            ),
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    }
]


def parse_request(text: str, settings: AppSettings) -> documents.DocQuery:
    today = datetime.now(ZoneInfo(settings.business_hours.timezone)).date()
    return documents.parse(text, today)


async def search(
    tools: ToolCaller, text: str, token: str, settings: AppSettings
) -> list[dict[str, Any]] | None:
    """Документы клиента по запросу; None — сообщение не про документы."""
    query = parse_request(text, settings)
    if not query.is_request:
        return None
    args: dict[str, Any] = {"query": text}
    if query.doc_type:
        args["type"] = query.doc_type
    if query.date_from:
        args["date_from"] = query.date_from.isoformat()
    if query.date_to:
        args["date_to"] = query.date_to.isoformat()
    if query.number:
        args["number"] = query.number
    hits = await tools.call("docs", "search_documents", args, token)
    return list(hits or [])


def is_match(docs: list[dict[str, Any]] | None) -> bool:
    """Однозначно найден ровно один документ."""
    return docs is not None and len(docs) == 1


def choices(docs: list[dict[str, Any]] | None) -> list[tuple[int, str]]:
    """Кнопки выбора: (id, «название · дата»), не больше `CHOICES_LIMIT` (как список /docs)."""
    out: list[tuple[int, str]] = []
    for d in (docs or [])[:CHOICES_LIMIT]:
        title, day = str(d.get("title") or ""), d.get("doc_date")
        out.append((int(d["document_id"]), f"{title} · {day}" if day else title))
    return out


def documents_block(docs: list[dict[str, Any]] | None) -> str:
    return prompts.xml_items(
        "document",
        [
            (
                {
                    "type": d.get("type") or "",
                    "date": str(d.get("doc_date") or ""),
                    "number": d.get("number") or "",
                },
                str(d.get("title") or ""),
            )
            for d in docs or []
        ],
    )
