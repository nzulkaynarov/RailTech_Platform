"""ERP MCP Tools implementation (CONTRACTS §5, packages/contracts/mcp-tools.json).

Каждый инструмент:
- Не принимает идентификаторов клиента/компании в аргументах (строго из context)
- Проверяет режим context.mode ("prospect" vs "customer")
- Изолирует данные чужих компаний ("чужой клиент — пустой результат")
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db import transaction
from jsonschema import Draft202012Validator, FormatChecker
from parties.models import Company
from portal.models import PortalRequestLine

from catalog.constants import MODE_CLIENT, MODE_LEAD
from catalog.published import project_many, published_products
from crm.models import Deal, DealStage, GeneratedDocument

from ..services.summary import (
    _map_doc_kind,
    delivery_lines,
    get_deal_detail_data,
    get_document_link_data,
    list_company_deals_data,
)
from ..services.webhooks import build_actor, emit_request_created
from .context import AgentContext

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Ошибка выполнения инструмента (некорректные параметры, недоступный режим и т.п.)."""


class InvalidArgumentsError(Exception):
    """Аргументы вызова не соответствуют `input_schema` инструмента (HTTP 400 `INVALID_ARGUMENTS`)."""

    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ToolModeError(ToolExecutionError):
    """Инструмент недоступен в текущем режиме агента (например, prospect)."""


# ─────────────────────────────────────────────────────────────────────────────
# Реализации инструментов (CONTRACTS §5)
# ─────────────────────────────────────────────────────────────────────────────


def list_client_deals_tool(context: AgentContext, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Сделки клиента со стадией и следующим шагом."""
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("list_client_deals is only available in customer mode")

    deals = list_company_deals_data(context.erp_company_id)
    return deals if deals is not None else []


def get_deal_status_tool(context: AgentContext, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Стадия сделки, КП, счета, поставки (проекция клиента), акты.

    Чужая сделка возвращает None (пустой результат).
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("get_deal_status is only available in customer mode")

    erp_deal_id = arguments.get("erp_deal_id")
    if erp_deal_id is None or not isinstance(erp_deal_id, int):
        raise ToolExecutionError("erp_deal_id integer required")

    deal = Deal.objects.filter(pk=erp_deal_id).first()
    if not deal or deal.company_id != context.erp_company_id:
        # Cross-tenant изоляция: чужой клиент — пустой результат
        return None

    return get_deal_detail_data(erp_deal_id, client_view=True)


def get_delivery_status_tool(context: AgentContext, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Строки поставки: статус, ожидаемая дата, трек. Без поставщика и цен.

    Чужая сделка возвращает пустой массив.
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("get_delivery_status is only available in customer mode")

    erp_deal_id = arguments.get("erp_deal_id")
    if erp_deal_id is None or not isinstance(erp_deal_id, int):
        raise ToolExecutionError("erp_deal_id integer required")

    deal = Deal.objects.filter(pk=erp_deal_id).first()
    if not deal or deal.company_id != context.erp_company_id:
        return []

    return delivery_lines(deal)


def list_client_documents_tool(context: AgentContext, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Документы клиента с фильтром по виду и датам."""
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("list_client_documents is only available in customer mode")

    qs = (
        GeneratedDocument.objects.filter(deal__company_id=context.erp_company_id)
        .select_related("template__kind", "deal")
        .order_by("-created_at")
    )

    date_from = arguments.get("date_from")
    if date_from:
        try:
            qs = qs.filter(created_at__date__gte=date_from)
        except Exception:
            pass

    date_to = arguments.get("date_to")
    if date_to:
        try:
            qs = qs.filter(created_at__date__lte=date_to)
        except Exception:
            pass

    kind_filter = arguments.get("kind")
    if kind_filter:
        kind_filter = str(kind_filter).lower().strip()

    result = []
    for d in qs:
        kind = _map_doc_kind(d.template.kind.code if d.template else "")
        if kind_filter and kind != kind_filter:
            continue
        status_code = d.status.code.lower() if hasattr(d.status, "code") else str(d.status or "issued").lower()
        result.append(
            {
                "erp_document_id": d.id,
                "erp_deal_id": d.deal_id,
                "kind": kind,
                "number": d.number or f"DOC-{d.id}",
                "date": d.created_at.date().isoformat(),
                "title": d.title or f"Документ {d.number}",
                "status": status_code,
            }
        )
    return result


def get_document_link_tool(context: AgentContext, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Подписанный URL файла на 10 минут; бот отправляет файл клиенту.

    Выдача пишется в аудит ERP. Чужой документ возвращает None.
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("get_document_link is only available in customer mode")

    erp_document_id = arguments.get("erp_document_id")
    if erp_document_id is None or not isinstance(erp_document_id, int):
        raise ToolExecutionError("erp_document_id integer required")

    doc = GeneratedDocument.objects.filter(pk=erp_document_id).select_related("deal__company").first()
    if not doc or not doc.deal or doc.deal.company_id != context.erp_company_id:
        return None

    crm_context = f"erp-mcp:client={context.crm_client_id}:company={context.erp_company_id}"
    return get_document_link_data(erp_document_id, crm_context=crm_context)


def search_catalog_tool(context: AgentContext, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Поиск по опубликованному слою каталога.

    prospect: название, описание, единица (без цен и наличия).
    customer: + цена (или «по запросу»), наличие, срок.
    """
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolExecutionError("query is required")

    top_k_raw = arguments.get("top_k", 5)
    try:
        top_k = max(1, min(int(top_k_raw or 5), 20))
    except (ValueError, TypeError):
        top_k = 5

    # Только проекция опубликованного слоя: ключи CatalogItem, без sku и остального внутреннего слоя.
    # Режим lead (prospect) — без price, availability и lead_time_days.
    catalog_mode = MODE_CLIENT if context.mode == "customer" else MODE_LEAD
    products = list(published_products().filter(name__icontains=query)[:top_k])
    return project_many(products, mode=catalog_mode)


@transaction.atomic
def create_request_tool(context: AgentContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Заявка в ERP от имени клиента: модель предлагает текст, код решает, что это «запрос».

    ERP шлёт CRM событие request.created(source=crm).
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("create_request is only available in customer mode")

    summary = str(arguments.get("summary") or "").strip()
    if not summary:
        raise ToolExecutionError("summary is required")

    lines_raw = arguments.get("lines")
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise ToolExecutionError("lines array must contain at least 1 item")

    company = Company.objects.filter(pk=context.erp_company_id).first()
    if not company:
        raise ToolExecutionError(f"Company #{context.erp_company_id} not found")

    primary_contact = company.contacts.filter(is_primary=True).first() or company.contacts.first()
    request_stage = DealStage.objects.filter(code="request").first()

    deal = Deal.objects.create(
        company=company,
        contact=primary_contact,
        stage=request_stage,
        title=f"Заявка: {company.name}",
        notes=summary,
    )

    for idx, item in enumerate(lines_raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        qty_val = None
        if item.get("quantity") is not None:
            try:
                qty_val = Decimal(str(item["quantity"]).replace(",", "."))
            except Exception:
                pass

        PortalRequestLine.objects.create(
            deal=deal,
            text=text,
            quantity=qty_val,
            unit=item.get("unit") or None,
            sort_order=idx + 1,
        )

    # Событие request.created в CRM
    emit_request_created(
        deal=deal,
        source="crm",
        actor=build_actor(actor_type="client", name="CRM Agent"),
        send_async=True,
        crm_client_id=context.crm_client_id,
    )

    stage_code = deal.stage.code if deal.stage else "request"
    return {
        "erp_request_id": deal.id,
        "number": f"D-{deal.id}",
        "status": stage_code,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Реестр инструментов (соответствие packages/contracts/mcp-tools.json)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS_METADATA = [
    {
        "name": "list_client_deals",
        "modes": ["customer"],
        "description": "Сделки клиента со стадией и следующим шагом.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "handler": list_client_deals_tool,
    },
    {
        "name": "get_deal_status",
        "modes": ["customer"],
        "description": "Стадия сделки, КП, счета, поставки (проекция клиента), акты.",
        "inputSchema": {
            "type": "object",
            "required": ["erp_deal_id"],
            "properties": {"erp_deal_id": {"type": "integer"}},
            "additionalProperties": False,
        },
        "handler": get_deal_status_tool,
    },
    {
        "name": "get_delivery_status",
        "modes": ["customer"],
        "description": "Строки поставки: статус, ожидаемая дата, трек. Без поставщика и цен.",
        "inputSchema": {
            "type": "object",
            "required": ["erp_deal_id"],
            "properties": {"erp_deal_id": {"type": "integer"}},
            "additionalProperties": False,
        },
        "handler": get_delivery_status_tool,
    },
    {
        "name": "list_client_documents",
        "modes": ["customer"],
        "description": "Документы клиента с фильтром по виду и датам.",
        "inputSchema": {
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
        "handler": list_client_documents_tool,
    },
    {
        "name": "get_document_link",
        "modes": ["customer"],
        "description": "Подписанный URL файла на 10 минут; бот отправляет файл клиенту. Выдача пишется в аудит ERP.",
        "inputSchema": {
            "type": "object",
            "required": ["erp_document_id"],
            "properties": {"erp_document_id": {"type": "integer"}},
            "additionalProperties": False,
        },
        "handler": get_document_link_tool,
    },
    {
        "name": "search_catalog",
        "modes": ["prospect", "customer"],
        "description": (
            "Поиск по опубликованному слою каталога. "
            "prospect: название, описание, единица. "
            "customer: + цена (или «по запросу»), наличие, срок. "
            "Цены лиду не называются (DECISIONS 2026-10-13)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "additionalProperties": False,
        },
        "handler": search_catalog_tool,
    },
    {
        "name": "create_request",
        "modes": ["customer"],
        "description": (
            "Заявка в ERP от имени клиента: модель предлагает текст, код решает, что это «запрос» "
            "(ORCHESTRATOR §3.4). ERP шлёт CRM событие request.created(source=crm)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["summary", "lines"],
            "properties": {
                "summary": {"type": "string", "minLength": 1, "maxLength": 5000},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string", "minLength": 1, "maxLength": 1000},
                            "quantity": {"type": ["string", "null"]},
                            "unit": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        "handler": create_request_tool,
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS_METADATA}


def validate_arguments(tool_meta: Dict[str, Any], arguments: Any) -> None:
    """Проверка аргументов по `input_schema` из контракта (packages/contracts/mcp-tools.json)."""
    validator = Draft202012Validator(tool_meta["inputSchema"], format_checker=FormatChecker())
    errors = sorted(
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(arguments)
    )
    if errors:
        raise InvalidArgumentsError(errors)


def execute_tool(context: AgentContext, tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Диспетчеризация и запуск инструмента."""
    tool_meta = TOOLS_BY_NAME.get(tool_name)
    if not tool_meta:
        raise ToolExecutionError(f"Tool '{tool_name}' not found")

    validate_arguments(tool_meta, arguments)
    handler = tool_meta["handler"]
    return handler(context, arguments)
