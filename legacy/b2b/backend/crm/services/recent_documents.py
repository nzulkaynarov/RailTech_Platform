"""«Недавние документы» — cross-type recent-documents feed for the dashboard widget (Rule 8).

Aggregates the newest КП (Quote), контракты (Contract), инвойсы (Invoice), акты (Act) and
сгенерированные документы (GeneratedDocument) a viewer may see into ONE date-sorted list, giving
the SPA the «единая станция документов» feeling. Read-only.

Company-scoping is IDENTICAL to each type's own ViewSet, so this feed can never surface a document
the viewer couldn't already open — in particular the hidden-competition boundary (ADR-0003 §5) is
preserved: a routed seller never sees a CO-ROUTED competitor's contract/invoice/act, nor another
company's DRAFT сгенерированный документ. The scoping helpers are REUSED (not re-derived) to keep
this feed from drifting away from the canonical querysets.
"""

from typing import List, Optional

MIN_LIMIT = 1
MAX_LIMIT = 20
DEFAULT_LIMIT = 8


def clamp_limit(raw, default: int = DEFAULT_LIMIT) -> int:
    """Coerce a caller-supplied limit into [MIN_LIMIT, MAX_LIMIT]; fall back to `default`."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(MIN_LIMIT, min(MAX_LIMIT, value))


def _user_company_ids(user) -> list:
    return list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))


def _is_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False))


def _recent_quotes(user, request, limit: int) -> List[dict]:
    """КП visible to the viewer — same scope as QuoteViewSet.get_queryset."""
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
    return [
        {
            "type": "quote",
            "id": quote.id,
            "label": quote.number or f"КП v{quote.version}",
            "status_code": quote.status.code if quote.status_id else None,
            "_date": quote.created_at,
            "deal": quote.deal_id,
            "hash": f"deal-quote/{quote.deal_id}",
        }
        for quote in qs[:limit]
    ]


def _recent_contracts(user, request, limit: int) -> List[dict]:
    """Контракты — same scope as ContractViewSet.get_queryset (billing visibility Q)."""
    from crm.models import Contract
    from crm.views.billing import _billing_visibility_q

    qs = Contract.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(
            _billing_visibility_q(user, request, deal_path="deal", seller_path="quote__seller_company_id")
        ).distinct()
    return [
        {
            "type": "contract",
            "id": contract.id,
            "label": contract.number,
            "status_code": contract.status_code,
            "_date": contract.created_at,
            "deal": contract.deal_id,
            "hash": "contracts",
        }
        for contract in qs[:limit]
    ]


def _recent_invoices(user, request, limit: int) -> List[dict]:
    """Инвойсы — same scope as InvoiceViewSet.get_queryset (incl. the DRAFT gate: a DRAFT invoice
    is the seller's private working copy, hidden from the buyer until ISSUED)."""
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
        qs = qs.filter(visibility_q & draft_gate).distinct()
    return [
        {
            "type": "invoice",
            "id": invoice.id,
            "label": invoice.number,
            "status_code": invoice.status_code,
            "_date": invoice.created_at,
            "deal": invoice.deal_id,
            "hash": f"invoices?open={invoice.id}",
        }
        for invoice in qs[:limit]
    ]


def _recent_acts(user, request, limit: int) -> List[dict]:
    """Акты — same scope as ActViewSet.get_queryset (billing visibility via invoice→contract→КП)."""
    from crm.models import Act
    from crm.views.billing import _billing_visibility_q

    qs = Act.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(
            _billing_visibility_q(
                user, request, deal_path="deal", seller_path="invoice__contract__quote__seller_company_id"
            )
        ).distinct()
    return [
        {
            "type": "act",
            "id": act.id,
            "label": act.number,
            "status_code": act.status_code,
            "_date": act.created_at,
            "deal": act.deal_id,
            "hash": "acts",
        }
        for act in qs[:limit]
    ]


def _recent_generated(user, request, limit: int) -> List[dict]:
    """Сгенерированные документы — same scope as GeneratedDocumentViewSet.get_queryset
    (own-company any-status + counterparties' ISSUED via party_visible_document_q; never another
    company's DRAFT/CANCELLED)."""
    from django.db.models import Q

    from crm.models import GeneratedDocument
    from crm.services.generated_documents import party_visible_document_q

    qs = GeneratedDocument.objects.select_related("status").order_by("-created_at")
    if not _is_admin(user):
        qs = qs.filter(Q(company_id__in=_user_company_ids(user)) | party_visible_document_q(user)).distinct()
    return [
        {
            "type": "generated",
            "id": document.id,
            "label": document.title or document.number,
            "status_code": document.status_code,
            "_date": document.created_at,
            "deal": document.deal_id,
            "hash": "other-documents",
        }
        for document in qs[:limit]
    ]


def recent_documents(user, request, limit: Optional[int] = DEFAULT_LIMIT) -> List[dict]:
    """Newest documents across all types the viewer may see, date-desc, capped at `limit`.

    Each per-type queryset is scoped exactly like its own ViewSet and pre-sliced to `limit`, so the
    global top-`limit` (a subset of the per-type union) is exact without scanning whole tables.
    """
    limit = clamp_limit(limit)
    entries = (
        _recent_quotes(user, request, limit)
        + _recent_contracts(user, request, limit)
        + _recent_invoices(user, request, limit)
        + _recent_acts(user, request, limit)
        + _recent_generated(user, request, limit)
    )
    entries.sort(key=lambda entry: entry["_date"], reverse=True)
    trimmed = entries[:limit]
    for entry in trimmed:
        entry["date"] = entry.pop("_date").isoformat()
    return trimmed
