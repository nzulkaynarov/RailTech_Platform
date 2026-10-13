"""Сквозной поиск по документам — cross-type textual search over the «единая станция документов»
(Odoo/B24-style global search for company users). Read-only.

Reuses the EXACT per-type company-scoping of `crm.services.recent_documents` (imported, not
re-derived), then narrows each scoped queryset by a case-insensitive `q` over the relevant text
fields, merges the heterogeneous rows, sorts by date-desc and caps at `limit`. Because the scope is
identical to each type's own ViewSet, search can never surface a document the viewer couldn't open:
the hidden-competition boundary (ADR-0003 §5) and the another-company-DRAFT gate are preserved.

Result element shape is IDENTICAL to recent_documents ({type,id,label,status_code,date,deal}).
A query shorter than MIN_QUERY_LEN returns [] WITHOUT touching the DB.
"""

from typing import List

from crm.services.recent_documents import (  # noqa: F401 — shared helpers, single source of truth
    DEFAULT_LIMIT,
    _is_admin,
    _user_company_ids,
    clamp_limit,
)

from .fulfillment import delivery_note_number

MIN_QUERY_LEN = 2


def _search_quotes(user, request, query: str, limit: int) -> List[dict]:
    """КП matching `query` on number / deal title — same scope as QuoteViewSet.get_queryset."""
    from django.db.models import Q

    from accounts.services.permissions import seller_visible_deal_ids
    from crm.models import Quote
    from crm.services.quotes import scope_quotes_for_viewer

    qs = Quote.objects.select_related("deal", "status").order_by("-created_at")
    if not _is_admin(user):
        visible_deal_ids = seller_visible_deal_ids(user, request)
        if visible_deal_ids is not None:
            qs = scope_quotes_for_viewer(qs.filter(deal_id__in=visible_deal_ids), user, request)
        else:
            qs = qs.filter(deal__company_id__in=_user_company_ids(user))
    qs = qs.filter(Q(number__icontains=query) | Q(deal__title__icontains=query))
    return [
        {
            "type": "quote",
            "id": quote.id,
            "label": quote.number or f"КП v{quote.version}",
            "status_code": quote.status.code if quote.status_id else None,
            "_date": quote.created_at,
            "deal": quote.deal_id,
        }
        for quote in qs[:limit]
    ]


def _search_contracts(user, request, query: str, limit: int) -> List[dict]:
    """Контракты matching `query` on number / deal title — same scope as ContractViewSet."""
    from django.db.models import Q

    from crm.models import Contract
    from crm.views.billing import _billing_visibility_q

    qs = Contract.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(_billing_visibility_q(user, request, deal_path="deal", seller_path="quote__seller_company_id"))
    qs = qs.filter(Q(number__icontains=query) | Q(deal__title__icontains=query)).distinct()
    return [
        {
            "type": "contract",
            "id": contract.id,
            "label": contract.number,
            "status_code": contract.status_code,
            "_date": contract.created_at,
            "deal": contract.deal_id,
        }
        for contract in qs[:limit]
    ]


def _search_invoices(user, request, query: str, limit: int) -> List[dict]:
    """Инвойсы matching `query` on number / deal title — same scope as InvoiceViewSet (DRAFT gate:
    a DRAFT invoice is the seller's private working copy, hidden from the buyer until ISSUED)."""
    from django.db.models import Q

    from crm.constants import InvoiceStatusCode
    from crm.models import Invoice
    from crm.views.billing import _invoice_seller_side_q

    qs = Invoice.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        buyer_q = Q(deal__company_id__in=_user_company_ids(user))
        seller_side_q = _invoice_seller_side_q(user, request)
        visibility_q = buyer_q if seller_side_q is None else (buyer_q | seller_side_q)
        draft_gate = ~Q(status__code=InvoiceStatusCode.DRAFT)
        if seller_side_q is not None:
            draft_gate = draft_gate | seller_side_q
        qs = qs.filter(visibility_q & draft_gate)
    qs = qs.filter(Q(number__icontains=query) | Q(deal__title__icontains=query)).distinct()
    return [
        {
            "type": "invoice",
            "id": invoice.id,
            "label": invoice.number,
            "status_code": invoice.status_code,
            "_date": invoice.created_at,
            "deal": invoice.deal_id,
        }
        for invoice in qs[:limit]
    ]


def _search_acts(user, request, query: str, limit: int) -> List[dict]:
    """Акты matching `query` on number / deal title — same scope as ActViewSet."""
    from django.db.models import Q

    from crm.models import Act
    from crm.views.billing import _billing_visibility_q

    qs = Act.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(
            _billing_visibility_q(
                user, request, deal_path="deal", seller_path="invoice__contract__quote__seller_company_id"
            )
        )
    qs = qs.filter(Q(number__icontains=query) | Q(deal__title__icontains=query)).distinct()
    return [
        {
            "type": "act",
            "id": act.id,
            "label": act.number,
            "status_code": act.status_code,
            "_date": act.created_at,
            "deal": act.deal_id,
        }
        for act in qs[:limit]
    ]


def _search_generated(user, request, query: str, limit: int) -> List[dict]:
    """Сгенерированные документы matching `query` on title / number / deal title — same scope as
    GeneratedDocumentViewSet (own-company any-status + counterparties' ISSUED; never another
    company's DRAFT/CANCELLED)."""
    from django.db.models import Q

    from crm.models import GeneratedDocument
    from crm.services.generated_documents import party_visible_document_q

    qs = GeneratedDocument.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(Q(company_id__in=_user_company_ids(user)) | party_visible_document_q(user))
    qs = qs.filter(Q(title__icontains=query) | Q(number__icontains=query) | Q(deal__title__icontains=query)).distinct()
    return [
        {
            "type": "generated",
            "id": document.id,
            "label": document.title or document.number,
            "status_code": document.status_code,
            "_date": document.created_at,
            "deal": document.deal_id,
        }
        for document in qs[:limit]
    ]


def _search_receipts(user, request, query: str, limit: int) -> List[dict]:
    """Квитанции (D2a) по номеру квитанции / счёта — видимость как у recent_documents."""
    from django.db.models import Q

    from crm.models import Invoice, Payment
    from crm.views.billing import _invoice_seller_side_q

    qs = Payment.objects.exclude(receipt_number="").select_related("invoice").order_by("-created_at")
    if not _is_admin(user):
        buyer_q = Q(invoice__deal__company_id__in=_user_company_ids(user))
        seller_q = _invoice_seller_side_q(user, request)
        if seller_q is not None:
            invoice_ids = Invoice.objects.filter(seller_q).values_list("id", flat=True)
            qs = qs.filter(buyer_q | Q(invoice_id__in=invoice_ids))
        else:
            qs = qs.filter(buyer_q)
    qs = qs.filter(Q(receipt_number__icontains=query) | Q(invoice__number__icontains=query)).distinct()
    return [
        {
            "type": "receipt",
            "id": payment.id,
            "label": payment.receipt_number,
            "status_code": "ISSUED",
            "_date": payment.created_at,
            "deal": payment.invoice.deal_id,
        }
        for payment in qs[:limit]
    ]


def _search_delivery_notes(user, request, query: str, limit: int) -> List[dict]:
    """Накладные (D2b) по треку / перевозчику / номеру договора."""
    from django.db.models import Q

    from crm.models import Fulfillment
    from crm.views.billing import _seller_side_q

    qs = Fulfillment.objects.filter(shipped_at__isnull=False).select_related("deal", "status").order_by("-shipped_at")
    if not _is_admin(user):
        buyer_q = Q(deal__company_id__in=_user_company_ids(user))
        seller_q = _seller_side_q(user, request, deal_path="deal", seller_path="contract__quote__seller_company_id")
        qs = qs.filter(buyer_q if seller_q is None else (buyer_q | seller_q))
    qs = qs.filter(
        Q(tracking_number__icontains=query) | Q(carrier__icontains=query) | Q(contract__number__icontains=query)
    ).distinct()
    return [
        {
            "type": "delivery_note",
            "id": fulfillment.id,
            "label": delivery_note_number(fulfillment),
            "status_code": fulfillment.status.code if fulfillment.status_id else "",
            "_date": fulfillment.shipped_at,
            "deal": fulfillment.deal_id,
        }
        for fulfillment in qs[:limit]
    ]


def search_documents(user, request, q, limit=DEFAULT_LIMIT) -> List[dict]:
    """Documents across all types the viewer may see whose text matches `q`, date-desc, capped.

    Each per-type queryset is scoped exactly like its own ViewSet, narrowed by `q` (icontains) and
    pre-sliced to `limit`, so the global top-`limit` is exact without scanning whole tables. A query
    shorter than MIN_QUERY_LEN short-circuits to [] with no DB access.
    """
    query = (q or "").strip()
    if len(query) < MIN_QUERY_LEN:
        return []
    limit = clamp_limit(limit)
    entries = (
        _search_quotes(user, request, query, limit)
        + _search_contracts(user, request, query, limit)
        + _search_invoices(user, request, query, limit)
        + _search_acts(user, request, query, limit)
        + _search_generated(user, request, query, limit)
        + _search_receipts(user, request, query, limit)
        + _search_delivery_notes(user, request, query, limit)
    )
    entries.sort(key=lambda entry: entry["_date"], reverse=True)
    trimmed = entries[:limit]
    for entry in trimmed:
        entry["date"] = entry.pop("_date").isoformat()
    return trimmed
