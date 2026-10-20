"""Company, Deal, and Document query service for CRM (CONTRACTS §2, M3-ERP-01; проекции по контракту 0.2.0 — FIX-30).

Строго изолирует внутренний слой бэк-офиса:
- Только клиентская проекция (никаких поставщиков, закупочных цен, себестоимости и маржи).
- Подписанные временные ссылки на файлы документов (10 минут, журнал ERP) — `documents_link.py` (FIX-32).

Форма ответов — `packages/contracts/openapi/erp-integration.yaml` (сторож: `integration/tests/test_contract_integration.py`).
Стадия и сумма сделки — только из `stages.py`; статусы договора, счёта и акта, видимость документов, деньги и сроки —
из `portal/projections.py` (те же функции, что у Cabinet, без копий). Нет данных — `None`, а не выдумка.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.utils import timezone
from parties.models import Company
from portal import projections
from sales.models import DeliveryLine, DeliveryLineStatus, Fulfillment
from sales.services.delivery_lines import sync_delivery_lines

from crm.constants import InvoiceStatusCode, QuoteStatusCode
from crm.models import Deal, Invoice

from ..models import CrmClientMapping
from . import documents_link, stages

logger = logging.getLogger(__name__)


def _map_doc_kind(raw_kind: str) -> str:
    kind = str(raw_kind or "").lower()
    mapping = {
        "quote": "quote",
        "kp": "quote",
        "contract": "contract",
        "dogovor": "contract",
        "invoice": "invoice",
        "schet": "invoice",
        "act": "act",
        "waybill": "waybill",
        "receipt": "receipt",
    }
    return mapping.get(kind, "other")


def _quote_status(quote) -> str:
    """`QuoteStatus` контракта. Отправленные и решённые — проекция портала; до отправки CRM видит `draft`/`approval`."""
    code = quote.status.code if quote.status_id else QuoteStatusCode.DRAFT
    if code in projections.CLIENT_QUOTE_STATUSES:
        return projections.quote_status(quote)
    return "draft" if code == QuoteStatusCode.DRAFT else "approval"


# ── Поставки ────────────────────────────────────────────────────────────────────────────────────────

#: Строки, по которым поставка ещё впереди (`next_delivery`): доставленное и решённое клиентом не «ближайшее».
_PENDING_DELIVERY = (
    DeliveryLineStatus.ASSEMBLING,
    DeliveryLineStatus.IN_TRANSIT,
    DeliveryLineStatus.READY_TO_SHIP,
    DeliveryLineStatus.SHIPPED,
)


def _delivery_line_item(line: DeliveryLine) -> Dict[str, Any]:
    """`DeliveryLine` контракта: без поставщика, цен и себестоимости; нет количества или единицы — `None`."""
    return {
        "erp_deal_id": line.deal_id,
        "line_no": line.line_no,
        "title": line.title,
        "quantity": str(line.quantity) if line.quantity is not None else None,
        "unit": projections.blank_to_none(line.unit),
        "status": line.status,
        "eta": line.eta.isoformat() if line.eta else None,
        "tracking": projections.blank_to_none(line.tracking),
        "accepted_at": line.accepted_at.isoformat() if line.accepted_at else None,
        "remark": projections.blank_to_none(line.remark),
    }


def delivery_lines(deal: Deal) -> List[Dict[str, Any]]:
    """Строки поставки сделки в проекции клиента (`DeliveryLine`) — те же `sales.DeliveryLine`, что видит Cabinet.

    Перед чтением строки доводятся до хода исполнения (`sync_delivery_lines`, идемпотентно, как при чтении из портала):
    иначе статус и срок были бы свежими, только если клиент недавно открывал Cabinet.
    """
    sync_delivery_lines(Fulfillment.objects.filter(deal=deal).select_related("status"))
    return [_delivery_line_item(line) for line in DeliveryLine.objects.filter(deal=deal).order_by("line_no")]


# ── Сделка ──────────────────────────────────────────────────────────────────────────────────────────


def _deal_item(deal: Deal, stage: str) -> Dict[str, Any]:
    """`DealListItem`: стадия и сумма — из `stages.py` (сумма `None`, пока клиенту не отправлено ни одно КП)."""
    amount = stages.deal_amount(deal)
    return {
        "erp_deal_id": deal.id,
        "number": projections.deal_number(deal),
        "title": deal.title or f"Сделка #{deal.id}",
        "stage": stage,
        "amount": projections.format_amount(amount) if amount is not None else None,
        "currency": stages.deal_currency(deal),
        "next_step": None,
        "updated_at": deal.updated_at.isoformat(),
    }


def _company_deals(company: Company) -> List[Deal]:
    """Сделки компании со всем, что читает `deal_stage`; строки поставки перед этим доводятся до хода исполнения."""
    sync_delivery_lines(Fulfillment.objects.filter(deal__company=company).select_related("status"))
    return list(stages.with_stage_facts(company.deals.all()).order_by("-updated_at"))


def _receivables(company: Company) -> Dict[str, str]:
    """Дебиторка: непогашенный остаток по выставленным счетам (выставлен, частично оплачен, просрочен).

    Контракт отдаёт одну сумму (`Money`). Счета в разных валютах не складываются: берётся валюта по умолчанию, если она
    есть среди долгов, иначе первая по алфавиту (Q-FIX30-2).
    """
    unpaid = Invoice.objects.filter(
        deal__company=company,
        status__code__in=[InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.OVERDUE],
    ).select_related("currency")
    totals: Dict[str, Decimal] = {}
    for invoice in unpaid:
        code = projections.currency_code(invoice.currency)
        totals[code] = totals.get(code, Decimal("0")) + max(invoice.balance_due, Decimal("0"))
    if not totals:
        return projections.money(Decimal("0"), projections.DEFAULT_CURRENCY)
    code = projections.DEFAULT_CURRENCY if projections.DEFAULT_CURRENCY in totals else sorted(totals)[0]
    return projections.money(totals[code], code)


def _next_delivery(open_deals: List[Deal]) -> Optional[Dict[str, Any]]:
    """Ближайшая поставка по открытым сделкам: из строк поставки, с самой ранней датой (без даты — в конце)."""
    lines = [line for deal in open_deals for line in deal.delivery_lines.all() if line.status in _PENDING_DELIVERY]
    if not lines:
        return None
    today = timezone.localdate()
    nearest = min(lines, key=lambda line: (line.eta is None, line.eta or today, line.deal_id, line.line_no))
    return _delivery_line_item(nearest)


def get_company_summary_data(erp_company_id: int) -> Optional[Dict[str, Any]]:
    """Сводка компании для карточки клиента в CRM."""
    company = Company.objects.filter(pk=erp_company_id).first()
    if not company:
        return None

    mapping = CrmClientMapping.objects.filter(company=company).first()
    crm_client_id = mapping.crm_client_id if mapping else company.id

    # Открытые сделки: закрытыми считаются `won`/`lost` по стадии контракта, а не по коду FSM
    deals = [(deal, stages.deal_stage(deal)) for deal in _company_deals(company)]
    open_deals = [(deal, stage) for deal, stage in deals if stages.is_open_stage(stage)]

    # Последний документ
    last_doc_obj = (
        documents_link.linkable_documents()
        .filter(deal__company=company)
        .select_related("template__kind", "status")
        .order_by("-created_at")
        .first()
    )
    last_document = None
    if last_doc_obj:
        kind = _map_doc_kind(last_doc_obj.template.kind.code if last_doc_obj.template else "")
        last_document = {
            "erp_document_id": last_doc_obj.id,
            "erp_deal_id": last_doc_obj.deal_id,
            "kind": kind,
            "number": last_doc_obj.number or f"DOC-{last_doc_obj.id}",
            "date": last_doc_obj.created_at.date().isoformat(),
            "title": last_doc_obj.title or f"Документ {last_doc_obj.number}",
            "status": (
                last_doc_obj.status.code.lower()
                if hasattr(last_doc_obj.status, "code")
                else str(last_doc_obj.status or "issued")
            ),
        }

    return {
        "erp_company_id": company.id,
        "crm_client_id": crm_client_id,
        "name": company.name,
        "open_deals": [_deal_item(deal, stage) for deal, stage in open_deals],
        "last_document": last_document,
        "receivables": _receivables(company),
        "next_delivery": _next_delivery([deal for deal, _ in open_deals]),
    }


def list_company_deals_data(erp_company_id: int) -> Optional[List[Dict[str, Any]]]:
    """Список всех сделок компании."""
    company = Company.objects.filter(pk=erp_company_id).first()
    if not company:
        return None

    return [_deal_item(deal, stages.deal_stage(deal)) for deal in _company_deals(company)]


def _signed_at(contract) -> Optional[str]:
    """Когда договор подписан: момент последней подписи у подписанного договора, иначе `None`."""
    if projections.contract_status(contract) != "signed":
        return None
    moments = [m for m in (contract.client_signed_at, contract.manager_signed_at) if m]
    return max(moments).isoformat() if moments else None


def get_deal_detail_data(erp_deal_id: int, *, client_view: bool = False) -> Optional[Dict[str, Any]]:
    """Детальная карточка сделки в клиентской проекции.

    `client_view=True` (erp-mcp, режим customer) — КП только отправленные, принятые и отклонённые:
    черновики и КП на согласовании клиенту не отдаются.
    """
    sync_delivery_lines(Fulfillment.objects.filter(deal_id=erp_deal_id).select_related("status"))
    deal = stages.with_stage_facts(Deal.objects.filter(pk=erp_deal_id)).first()
    if not deal:
        return None

    company = deal.company
    mapping = CrmClientMapping.objects.filter(company=company).first() if company else None
    crm_client_id = mapping.crm_client_id if mapping else (company.id if company else 0)

    # КП (новые версии — выше)
    quotes = []
    for q in sorted(deal.quotes.all(), key=lambda quote: quote.version, reverse=True):
        if client_view and (not q.status_id or q.status.code not in projections.CLIENT_QUOTE_STATUSES):
            continue
        quotes.append(
            {
                "erp_quote_id": q.id,
                "version": q.version,
                "status": _quote_status(q),
                "public_url": projections.quote_public_url(q),
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "total": projections.money(q.total_incl_vat, projections.currency_code(q.quote_currency)),
            }
        )

    # Договоры: только те, что видит клиент (на подписи и подписанные)
    contracts = [
        {
            "erp_contract_id": c.id,
            "number": c.number or f"CTR-{c.id}",
            "status": projections.contract_status(c),
            "signed_at": _signed_at(c),
        }
        for c in sorted(deal.contracts.all(), key=lambda contract: contract.created_at, reverse=True)
        if projections.client_contracts_visible(c)
    ]

    # Счета: не черновики и со сроком оплаты
    invoices = [
        {
            "erp_invoice_id": inv.id,
            "number": inv.number or f"INV-{inv.id}",
            "status": projections.invoice_status(inv),
            "total": projections.money(inv.total_incl_vat, projections.currency_code(inv.currency)),
            "paid": projections.money(inv.amount_paid, projections.currency_code(inv.currency)),
            "due_date": projections.invoice_due_date(inv).isoformat(),
        }
        for inv in sorted(deal.invoices.all(), key=lambda invoice: invoice.created_at, reverse=True)
        if projections.client_invoices_visible(inv)
    ]

    # Поставки (клиентская проекция — без поставщика, цен и себестоимости)
    deliveries = [_delivery_line_item(line) for line in sorted(deal.delivery_lines.all(), key=lambda x: x.line_no)]

    # Акты: выставленные, принятые и возвращённые
    acts = [
        {
            "erp_act_id": a.id,
            "number": a.number or f"ACT-{a.id}",
            "status": projections.act_status(a),
            "issued_at": projections.act_issued_at(a).isoformat(),
        }
        for a in sorted(deal.acts.all(), key=lambda act: act.created_at, reverse=True)
        if projections.client_acts_visible(a)
    ]

    return {
        **_deal_item(deal, stages.deal_stage(deal)),
        "erp_company_id": company.id if company else 0,
        "crm_client_id": crm_client_id,
        "quotes": quotes,
        "contracts": contracts,
        "invoices": invoices,
        "deliveries": deliveries,
        "acts": acts,
    }


def list_deal_documents_data(erp_deal_id: int) -> Optional[List[Dict[str, Any]]]:
    """Список документов сделки."""
    deal = Deal.objects.filter(pk=erp_deal_id).first()
    if not deal:
        return None

    docs = (
        documents_link.linkable_documents()
        .filter(deal=deal)
        .select_related("template__kind", "status")
        .order_by("-created_at")
    )
    result = []
    for d in docs:
        kind = _map_doc_kind(d.template.kind.code if d.template else "")
        result.append(
            {
                "erp_document_id": d.id,
                "erp_deal_id": deal.id,
                "kind": kind,
                "number": d.number or f"DOC-{d.id}",
                "date": d.created_at.date().isoformat(),
                "title": d.title or f"Документ {d.number}",
                "status": (d.status.code.lower() if hasattr(d.status, "code") else str(d.status or "issued")),
            }
        )
    return result


def get_document_link_data(erp_document_id: int, crm_context: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Подписанная ссылка на файл документа (10 минут): вся логика — `documents_link.issue_document_link` (FIX-32)."""
    return documents_link.issue_document_link(erp_document_id, crm_context)
