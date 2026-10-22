"""Реализации инструментов erp-mcp (CONTRACTS §5, packages/contracts/mcp-tools.json).

Имена, описания, режимы и схемы аргументов здесь НЕ объявляются: их задаёт контракт (`contract.py`), а модуль
отдаёт только функции-обработчики по имени инструмента (`HANDLERS`). Каждый инструмент:
- Не принимает идентификаторов клиента/компании в аргументах (строго из context)
- Проверяет режим context.mode ("prospect" vs "customer")
- Изолирует данные чужих компаний ("чужой клиент — пустой результат")
"""

from __future__ import annotations

import datetime
import json
import logging
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from parties.models import Company
from portal.models import PortalRequestLine
from portal.services import documents as portal_documents

from catalog.constants import MODE_CLIENT, MODE_LEAD
from catalog.published import project_many, published_products
from crm.models import Deal

from ..services import events
from ..services.stages import deal_stage, initial_fsm_stage
from ..services.summary import (
    delivery_lines,
    document_item,
    get_deal_detail_data,
    get_document_link_data,
    list_company_deals_data,
)
from .context import AgentContext
from .contract import ToolSpec

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Ошибка выполнения инструмента (некорректные параметры, недоступный режим и т.п.)."""


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


def _iso_date(value: Any) -> Optional[datetime.date]:
    """Дата фильтра `YYYY-MM-DD`; не дата — фильтр не применяется (как и раньше, без ошибки инструмента)."""
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def list_client_documents_tool(context: AgentContext, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Документы клиента с фильтром по виду и датам: ровно те, что видит клиент в портале (FIX-38).

    Выпущенные КП, договоры, счета, акты, накладные и `GeneratedDocument` с теми же id, что у `GET /documents` портала и
    у `get_document_link`; черновики, отменённые и внутренние документы не показываются.
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("list_client_documents is only available in customer mode")

    company = Company.objects.filter(pk=context.erp_company_id).first()
    if company is None:
        return []

    kind_filter = str(arguments.get("kind") or "").lower().strip()
    date_from = _iso_date(arguments["date_from"]) if arguments.get("date_from") else None
    date_to = _iso_date(arguments["date_to"]) if arguments.get("date_to") else None

    result = []
    for document in portal_documents.client_documents(company, kind=kind_filter or None):
        if (date_from and document.date < date_from) or (date_to and document.date > date_to):
            continue
        result.append(document_item(document))
    return result


def get_document_link_tool(context: AgentContext, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Подписанный URL файла на 10 минут; бот отправляет файл клиенту.

    Выдача пишется в аудит ERP с контекстом `{"crm_client_id", "channel": "bot"}` (журнал скачиваний знает канал).
    Чужой, невыпущенный и внутренний документ возвращает None.
    """
    if context.mode != "customer" or not context.erp_company_id:
        raise ToolModeError("get_document_link is only available in customer mode")

    erp_document_id = arguments.get("erp_document_id")
    if erp_document_id is None or not isinstance(erp_document_id, int):
        raise ToolExecutionError("erp_document_id integer required")

    company = Company.objects.filter(pk=context.erp_company_id).first()
    if company is None or portal_documents.find_client_document(company, erp_document_id) is None:
        return None

    crm_context = json.dumps({"crm_client_id": context.crm_client_id, "channel": "bot"})
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

    Событие request.created(source=crm) инструмент публикует на шину rt_bus сам, в транзакции создания заявки, — ровно одно:
    источник, актор и клиент CRM заданы здесь (как для портала, FIX-23); сбой публикации откатывает заявку.
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
        raise ToolExecutionError("company not found")

    primary_contact = company.contacts.filter(is_primary=True).first() or company.contacts.first()
    request_stage = initial_fsm_stage()

    deal = Deal(
        company=company,
        contact=primary_contact,
        stage=request_stage,
        title=f"Заявка: {company.name}",
        notes=summary,
    )
    deal.save()

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
            except (ArithmeticError, ValueError):
                pass  # количество не число — строка без количества, как указал клиент

        PortalRequestLine.objects.create(
            deal=deal,
            text=text,
            quantity=qty_val,
            unit=str(item.get("unit") or "").strip(),  # колонка NOT NULL; контракт разрешает `unit` null или без поля
            sort_order=idx + 1,
        )

    events.publish_request_created(
        deal,
        source="crm",
        erp_request_id=deal.id,
        summary=summary,
        actor=events.build_actor(actor_type="client", name="CRM Agent"),
        crm_client_id=context.crm_client_id,
    )
    return {
        "erp_request_id": deal.id,
        "number": f"D-{deal.id}",
        "status": deal_stage(deal),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Обработчики по имени инструмента. Состав имён сверяется с packages/contracts/mcp-tools.json
# (`assert_handlers_match_contract`) и тестом; схемы, режимы и описания живут только в контракте.
# ─────────────────────────────────────────────────────────────────────────────

HANDLERS = {
    "list_client_deals": list_client_deals_tool,
    "get_deal_status": get_deal_status_tool,
    "get_delivery_status": get_delivery_status_tool,
    "list_client_documents": list_client_documents_tool,
    "get_document_link": get_document_link_tool,
    "search_catalog": search_catalog_tool,
    "create_request": create_request_tool,
}


def assert_handlers_match_contract(tools: Iterable[str]) -> None:
    """Инструмент без обработчика или обработчик без инструмента в контракте — процесс не стартует."""
    declared = set(tools)
    missing = sorted(declared - set(HANDLERS))
    extra = sorted(set(HANDLERS) - declared)
    if missing or extra:
        raise RuntimeError(f"erp-mcp: контракт и обработчики расходятся (нет обработчика: {missing}, лишние: {extra})")


def execute_tool(context: AgentContext, spec: ToolSpec, arguments: Dict[str, Any]) -> Any:
    """Запуск обработчика инструмента из контракта; режим проверяется по `modes` контракта."""
    if context.mode not in spec.modes:
        raise ToolModeError(f"{spec.name} is not available in {context.mode} mode")
    return HANDLERS[spec.name](context, arguments)
