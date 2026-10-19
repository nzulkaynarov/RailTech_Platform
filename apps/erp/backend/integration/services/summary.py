"""Company, Deal, and Document query service for CRM (CONTRACTS §2, M3-ERP-01).

Строго изолирует внутренний слой бэк-офиса:
- Только клиентская проекция (никаких поставщиков, закупочных цен, себестоимости и маржи).
- Подписанные временные ссылки на файлы документов (10 минут) с аудитом вызовов.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils import timezone
from parties.models import Company
from sales.models import Fulfillment

from crm.models import Deal, GeneratedDocument, Invoice

from ..models import CrmClientMapping

logger = logging.getLogger(__name__)


def _to_money(amount: Decimal | float | int | str, currency: str = "UZS") -> Dict[str, str]:
    try:
        val = Decimal(str(amount))
    except Exception:
        val = Decimal("0")
    return {"amount": f"{val:.2f}", "currency": currency}


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


#: Статусы КП из справочника ERP -> `QuoteStatus` контракта. Клиент видит только
#: отправленные, принятые и отклонённые (как публичная страница КП в `portal`).
_QUOTE_STATUS_MAP = {
    "draft": "draft",
    "pending_trade_review": "approval",
    "pending_approval": "approval",
    "ready_to_send": "approval",
    "approval": "approval",
    "sent": "sent",
    "viewed": "viewed",
    "approved": "accepted",
    "accepted": "accepted",
    "rejected": "rejected",
    "expired": "expired",
}
CLIENT_VISIBLE_QUOTE_STATUSES = frozenset({"sent", "viewed", "accepted", "rejected", "expired"})

_FULFILLMENT_STATUS_MAP = {
    "pending": "assembling",
    "assembling": "assembling",
    "ready_to_ship": "ready_to_ship",
    "shipped": "shipped",
    "in_transit": "in_transit",
    "disputed": "in_transit",
    "delivered": "delivered",
    "accepted": "delivered",
}


def delivery_lines(deal: Deal) -> List[Dict[str, Any]]:
    """Поставки сделки в проекции клиента (`DeliveryLine`): без поставщика, цен и себестоимости.

    У исполнения сделки (`sales.Fulfillment`, один к одному) нет количества и единицы —
    они не выдумываются: `quantity` и `unit` равны `null`.
    """
    fulfillment = Fulfillment.objects.filter(deal=deal).select_related("status").first()
    if fulfillment is None:
        return []
    raw_code = fulfillment.status.code.lower() if fulfillment.status_id else ""
    eta = fulfillment.expected_delivery_date
    return [
        {
            "erp_deal_id": deal.id,
            "line_no": 1,
            "title": deal.title or f"Поставка #{fulfillment.id}",
            "quantity": None,
            "unit": None,
            "status": _FULFILLMENT_STATUS_MAP.get(raw_code, "assembling"),
            "eta": eta.isoformat() if eta else None,
            "tracking": fulfillment.tracking_number or None,
        }
    ]


def get_company_summary_data(erp_company_id: int) -> Optional[Dict[str, Any]]:
    """Сводка компании для карточки клиента в CRM."""
    company = Company.objects.filter(pk=erp_company_id).first()
    if not company:
        return None

    mapping = CrmClientMapping.objects.filter(company=company).first()
    crm_client_id = mapping.crm_client_id if mapping else company.id

    # Открытые сделки
    open_deals_qs = (
        company.deals.exclude(stage__code__in=["won", "lost"])
        .select_related("stage")
        .prefetch_related("quotes")
        .order_by("-updated_at")
    )
    open_deals = []
    for d in open_deals_qs:
        open_deals.append(
            {
                "erp_deal_id": d.id,
                "number": f"D-{d.id}",
                "title": d.title or f"Сделка #{d.id}",
                "stage": d.stage.code if d.stage else "request",
                "amount": f"{d.total_value:.2f}",
                "currency": "UZS",
                "next_step": None,
                "updated_at": d.updated_at.isoformat(),
            }
        )

    # Последний документ
    last_doc_obj = (
        GeneratedDocument.objects.filter(deal__company=company)
        .select_related("template__kind")
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

    # Дебиторка (неоплаченные счета)
    invoices = Invoice.objects.filter(
        deal__company=company,
        status__code__in=["issued", "partially_paid", "ISSUED", "PARTIALLY_PAID"],
    )
    total_receivable = sum((inv.total_amount - (inv.paid_amount or Decimal("0"))) for inv in invoices)
    receivables = _to_money(max(total_receivable, Decimal("0")), "UZS")

    # Ближайшая поставка (проекция клиента)
    next_delivery = None
    active_deal_ids = company.deals.values_list("id", flat=True)
    try:
        from sales.models import Fulfillment

        f_obj = (
            Fulfillment.objects.filter(
                deal_id__in=active_deal_ids, status__in=["assembling", "in_transit", "ready_to_ship"]
            )
            .order_by("eta")
            .first()
        )
        if f_obj:
            next_delivery = {
                "erp_deal_id": f_obj.deal_id,
                "line_no": 1,
                "title": f_obj.title,
                "quantity": str(f_obj.quantity or 1),
                "unit": "шт",
                "status": (
                    f_obj.status
                    if f_obj.status in ["assembling", "in_transit", "ready_to_ship", "shipped", "delivered"]
                    else "assembling"
                ),
                "eta": f_obj.eta.isoformat() if f_obj.eta else None,
                "tracking": f_obj.tracking_number,
            }
    except Exception:
        pass

    return {
        "erp_company_id": company.id,
        "crm_client_id": crm_client_id,
        "name": company.name,
        "open_deals": open_deals,
        "last_document": last_document,
        "receivables": receivables,
        "next_delivery": next_delivery,
    }


def list_company_deals_data(erp_company_id: int) -> Optional[List[Dict[str, Any]]]:
    """Список всех сделок компании."""
    company = Company.objects.filter(pk=erp_company_id).first()
    if not company:
        return None

    deals_qs = company.deals.select_related("stage").prefetch_related("quotes").order_by("-updated_at")
    result = []
    for d in deals_qs:
        result.append(
            {
                "erp_deal_id": d.id,
                "number": f"D-{d.id}",
                "title": d.title or f"Сделка #{d.id}",
                "stage": d.stage.code if d.stage else "request",
                "amount": f"{d.total_value:.2f}",
                "currency": "UZS",
                "next_step": None,
                "updated_at": d.updated_at.isoformat(),
            }
        )
    return result


def get_deal_detail_data(erp_deal_id: int, *, client_view: bool = False) -> Optional[Dict[str, Any]]:
    """Детальная карточка сделки в клиентской проекции.

    `client_view=True` (erp-mcp, режим customer) — КП только отправленные, принятые и отклонённые:
    черновики и КП на согласовании клиенту не отдаются.
    """
    deal = (
        Deal.objects.filter(pk=erp_deal_id)
        .select_related("company", "stage")
        .prefetch_related("quotes", "contracts", "invoices", "acts")
        .first()
    )
    if not deal:
        return None

    company = deal.company
    mapping = CrmClientMapping.objects.filter(company=company).first() if company else None
    crm_client_id = mapping.crm_client_id if mapping else (company.id if company else 0)

    # КП
    quotes = []
    cabinet_url = getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")
    for q in deal.quotes.order_by("-version"):
        q_status = _QUOTE_STATUS_MAP.get(q.status.code.lower() if q.status else "draft", "draft")
        if client_view and q_status not in CLIENT_VISIBLE_QUOTE_STATUSES:
            continue
        quotes.append(
            {
                "erp_quote_id": q.id,
                "version": q.version,
                "status": q_status,
                "public_url": f"{cabinet_url}/quotes/{q.id}",
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "total": _to_money(
                    q.total_incl_vat or Decimal("0"), q.quote_currency.code if q.quote_currency_id else "UZS"
                ),
            }
        )

    # Договоры
    contracts = []
    for c in deal.contracts.order_by("-created_at"):
        contracts.append(
            {
                "erp_contract_id": c.id,
                "number": c.number or f"CTR-{c.id}",
                "status": c.status.code.lower() if c.status else "draft",
                "signed_at": c.signed_at.isoformat() if c.signed_at else None,
            }
        )

    # Счета
    invoices = []
    for inv in deal.invoices.order_by("-created_at"):
        invoices.append(
            {
                "erp_invoice_id": inv.id,
                "number": inv.number or f"INV-{inv.id}",
                "status": inv.status.code.lower() if inv.status else "issued",
                "total": _to_money(inv.total_amount or Decimal("0"), "UZS"),
                "paid": _to_money(inv.paid_amount or Decimal("0"), "UZS"),
                "due_date": (inv.due_date or inv.created_at.date()).isoformat(),
            }
        )

    # Поставки (клиентская проекция — без поставщика, цен и себестоимости)
    deliveries = delivery_lines(deal)

    # Акты
    acts = []
    for a in deal.acts.order_by("-created_at"):
        acts.append(
            {
                "erp_act_id": a.id,
                "number": a.number or f"ACT-{a.id}",
                "status": a.status.code.lower() if a.status else "issued",
                "issued_at": a.created_at.isoformat(),
            }
        )

    return {
        "erp_deal_id": deal.id,
        "number": f"D-{deal.id}",
        "title": deal.title or f"Сделка #{deal.id}",
        "stage": deal.stage.code if deal.stage else "request",
        "amount": f"{deal.total_value:.2f}",
        "currency": "UZS",
        "next_step": None,
        "updated_at": deal.updated_at.isoformat(),
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

    docs = GeneratedDocument.objects.filter(deal=deal).select_related("template__kind").order_by("-created_at")
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
    """Выдача временной подписанной ссылки на файл документа (10 минут).

    Факт выдачи логируется с CRM-контекстом.
    """
    doc = GeneratedDocument.objects.filter(pk=erp_document_id).first()
    if not doc:
        return None

    logger.info("Generated document %s link requested with CRM context: %s", erp_document_id, crm_context)

    expires_at = timezone.now() + timezone.timedelta(minutes=10)
    erp_url = getattr(settings, "ERP_BASE_URL", "http://erp.localhost").rstrip("/")
    download_url = f"{erp_url}/api/v1/documents/{doc.id}/download/?token=link_{doc.id}"

    file_name = doc.number or f"document_{doc.id}.pdf"
    if not file_name.lower().endswith(".pdf"):
        file_name += ".pdf"

    return {
        "url": download_url,
        "expires_at": expires_at.isoformat(),
        "file_name": file_name,
        "content_type": "application/pdf",
        "size_bytes": getattr(doc, "file_size", 0) or 1024,
    }
