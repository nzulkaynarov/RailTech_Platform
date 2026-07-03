"""AI draft-КП generation (ADR-0006 Move 3 — speed).

A routed seller turns the buyer's request into a pre-filled draft КП in ONE click: the request lines
are copied into a new seller Quote, and matched products get cost / currency / lead-time prefilled
from the seller's own SupplierOffers (pricing-assist). The seller reviews-and-sends instead of
re-typing the whole КП — cutting time-to-first-КП (the wedge metric). Rule 8 service.
"""

import logging
from decimal import Decimal
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Max

from accounts.models import CustomUser
from crm.constants import QuoteStatusCode

from ..models import Deal, Quote, QuoteItem, QuoteStatus
from .pricing_assist import suggest_pricing_for_products

logger = logging.getLogger(__name__)

# Line-identity fields copied verbatim from a buyer request line → the seller's draft line.
_LINE_FIELDS = (
    "product_id",
    "imported_raw_name",
    "name_canonical",
    "quantity",
    "unit",
    "unit_code",
    "mpn",
    "gost_drawing",
    "hs_code",
    "note",
)


def _request_items(deal: Deal):
    """The buyer's request lines — items on the deal's UNCLAIMED request quote (prepared_by=None)."""
    request_quote = deal.quotes.filter(prepared_by__isnull=True).order_by("version").first()
    return list(request_quote.items.all()) if request_quote else []


def _resolve_exact_catalog_matches(request_items) -> dict:
    """Deterministically bind still-unmatched request lines to a catalog Product by EXACT
    identifier (GOST drawing, then MPN) — but ONLY when exactly one PUBLISHED product matches.

    This is the SAFE half of ADR-0006 Move 3 (auto-match to cut time-to-first-КП): an exact
    GOST/MPN hit is unambiguous, so it is auto-bound → pricing-assist can then prefill it, and the
    seller gets a fuller draft in one click. Fuzzy / trigram / AI matches deliberately do NOT
    auto-bind here — they stay human-confirmed (services_ai.match_lines_to_catalog / Smart Match),
    preserving the platform's "AI never binds unattended" principle. A line with an ambiguous
    identifier (2+ published matches) is left unmatched rather than guessed.

    Returns {request_item.pk: product_id} for the lines that were resolved.
    """
    from catalog.models import Product

    resolved: dict[int, int] = {}
    for src in request_items:
        if src.product_id:
            continue
        gost = (src.gost_drawing or "").strip()
        mpn = (src.mpn or "").strip()
        product_ids = []
        if gost:
            product_ids = list(
                Product.objects.filter(status__code="PUBLISHED", gost_drawing__iexact=gost).values_list(
                    "id", flat=True
                )[:2]
            )
        if len(product_ids) != 1 and mpn:
            product_ids = list(
                Product.objects.filter(status__code="PUBLISHED", manufacturer_part_number__iexact=mpn).values_list(
                    "id", flat=True
                )[:2]
            )
        if len(product_ids) == 1:
            resolved[src.pk] = product_ids[0]
    return resolved


@transaction.atomic
def generate_draft_quote(deal_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str], int]:
    """Build a pre-filled draft КП for `actor`'s seller company from the deal's buyer request.
    Returns (quote, error_code, prefilled_count). The quote is a fresh DRAFT owned by the actor's
    seller company — never touches the buyer request or a competitor's КП."""
    from accounts.services.permissions import (
        can_edit_quote_pricing,
        is_platform_admin_viewer,
        primary_seller_company_id,
        seller_company_routed_to_deal,
    )

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT", 0
    if not (getattr(actor, "is_superuser", False) or can_edit_quote_pricing(actor)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE", 0
    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        return None, "DEAL_NOT_FOUND", 0
    if not (getattr(actor, "is_superuser", False) or seller_company_routed_to_deal(actor, deal_id)):
        return None, "MEMBER_REQUIRED_FOR_ACTION", 0
    request_items = _request_items(deal)
    if not request_items:
        return None, "NO_REQUEST_LINES", 0

    seller_company_id = primary_seller_company_id(actor)
    # MONETIZATION GATE (ADR-0006 Move 4): AI draft is a paid accelerator. An operational subscription
    # grants it (unmetered) by the baseline; a credit-limited entitlement meters it. consume_credit
    # decrements only when metered, and the whole function is atomic so a credit rolls back on error.
    # Superuser = platform escalation (no seller company), bypasses.
    if not getattr(actor, "is_superuser", False):
        from accounts.constants import FeatureKey
        from accounts.services import consume_credit

        if not consume_credit(seller_company_id, FeatureKey.AI_DRAFT):
            return None, "AI_DRAFT_NOT_ENTITLED", 0
    version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1
    quote = Quote.objects.create(
        deal=deal,
        version=version,
        prepared_by=actor,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT),
        seller_company_id=seller_company_id,
    )
    # КП-level defaults (Incoterm / VAT / margin / validity) from the seller's CompanySettings.
    if seller_company_id:
        from accounts.models import Company

        from .quotes import apply_company_quote_defaults

        apply_company_quote_defaults(quote, Company.objects.filter(pk=seller_company_id).first())

    # Move 3: deterministically bind still-unmatched lines by exact GOST/MPN BEFORE pricing,
    # so pricing-assist covers the freshly-matched products too.
    resolved_matches = _resolve_exact_catalog_matches(request_items)
    effective_ids = [it.product_id or resolved_matches.get(it.pk) for it in request_items]
    pricing = (
        suggest_pricing_for_products([pid for pid in effective_ids if pid], seller_company_id)
        if seller_company_id
        else {}
    )
    prefilled = 0
    auto_matched = 0
    for src in request_items:
        data = {field: getattr(src, field) for field in _LINE_FIELDS}
        if not data["product_id"]:
            resolved_pid = resolved_matches.get(src.pk)
            if resolved_pid:
                data["product_id"] = resolved_pid
                auto_matched += 1
        product_id = data["product_id"]
        offer = pricing.get(product_id) if product_id else None
        if offer:
            data["frozen_base_price"] = Decimal(offer["base_price"])  # str (JSON-safe) → Decimal field
            data["lead_time_days"] = offer["lead_time_days"]
            if offer["currency"]:
                from master_data.models import Currency

                data["frozen_currency"] = Currency.objects.filter(code=offer["currency"]).first()
            prefilled += 1
        QuoteItem.objects.create(quote=quote, **data)

    if auto_matched:
        logger.info(
            "draft КП %s: auto-matched %s line(s) to catalog by exact identifier (GOST/MPN)",
            quote.id,
            auto_matched,
        )

    from .quotes import QuoteCalculationService

    QuoteCalculationService.recalculate_quote(quote.id)
    quote.refresh_from_db()
    return quote, None, prefilled
