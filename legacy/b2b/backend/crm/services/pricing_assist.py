"""Pricing-assist (ADR-0006 Move 3 — AI moat / speed).

Autofills a КП line's cost from the SELLER'S OWN active SupplierOffer for the matched catalog
Product, so a seller building a КП doesn't retype prices the platform already knows — cutting
time-to-first-КП (the wedge metric). Deterministic catalog lookup (NOT an LLM call): the seller
reviews the suggestion before sending. Strictly scoped to the seller's own offers — a competitor's
price is never surfaced (multi-seller confidentiality).
"""

from typing import Optional, Tuple

from django.db.models import Q
from django.utils import timezone

from catalog.models import SupplierOffer

from ..models import Quote


def suggest_line_pricing(product_id: Optional[int], seller_company_id: Optional[int]) -> Optional[dict]:
    """The seller's cheapest active, in-date SupplierOffer for `product_id` → fields to prefill a
    КП line. None when the seller has no offer for that product (they price it manually)."""
    if not product_id or not seller_company_id:
        return None
    today = timezone.localdate()
    offer = (
        SupplierOffer.objects.filter(product_id=product_id, supplier_id=seller_company_id, is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("currency", "delivery_basis")
        .order_by("base_price")
        .first()
    )
    if offer is None:
        return None
    return {
        "product_id": product_id,
        "offer_id": offer.id,
        "base_price": str(offer.base_price),
        "currency": offer.currency.code if offer.currency_id else None,
        # The buyer-facing line lead time = stock first, else order; KP cascade may split (Track B).
        "lead_time_days": offer.in_stock_lead_time_days or offer.order_lead_time_days or 0,
        "in_stock_lead_time_days": offer.in_stock_lead_time_days,
        "order_lead_time_days": offer.order_lead_time_days,
        "min_order_qty": offer.min_order_qty,
        "supplier_sku": offer.supplier_sku,
        "delivery_basis": offer.delivery_basis.code if offer.delivery_basis_id else None,
        "stock_quantity": offer.stock_quantity,
    }


def suggest_pricing_for_products(product_ids, seller_company_id: Optional[int]) -> dict:
    """Batch pricing-assist: {product_id: suggestion} for products the seller has an offer for.
    One query (no N+1); products without an offer are simply absent from the map."""
    ids = [pid for pid in set(product_ids or []) if pid]
    if not ids or not seller_company_id:
        return {}
    today = timezone.localdate()
    offers = (
        SupplierOffer.objects.filter(product_id__in=ids, supplier_id=seller_company_id, is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("currency", "delivery_basis")
        .order_by("product_id", "base_price")
    )
    # ordering puts the cheapest offer first per product → keep the first seen.
    out: dict = {}
    for offer in offers:
        if offer.product_id in out:
            continue
        out[offer.product_id] = {
            "product_id": offer.product_id,
            "offer_id": offer.id,
            "base_price": str(offer.base_price),
            "currency": offer.currency.code if offer.currency_id else None,
            "lead_time_days": offer.in_stock_lead_time_days or offer.order_lead_time_days or 0,
            "in_stock_lead_time_days": offer.in_stock_lead_time_days,
            "order_lead_time_days": offer.order_lead_time_days,
            "min_order_qty": offer.min_order_qty,
            "supplier_sku": offer.supplier_sku,
            "delivery_basis": offer.delivery_basis.code if offer.delivery_basis_id else None,
            "stock_quantity": offer.stock_quantity,
        }
    return out


def suggest_quote_pricing(quote_id: int, actor) -> Tuple[Optional[dict], Optional[str]]:
    """Pricing suggestions for every matched (product-linked) line of a КП, from the OWNING seller's
    SupplierOffers. Returns {"suggestions": [{item_id, product_id, base_price, currency, ...}]} for
    the lines that have an offer. Authorized by the cost-visibility gate (only the quote's own seller
    company sees its costs) — a competitor on the same multi-seller deal cannot peek (Rule 8 service).
    """
    from accounts.services.permissions import can_view_quote_costs_for

    from .quotes import _quote_owner_company_id

    quote = Quote.objects.select_related("deal").prefetch_related("items").filter(pk=quote_id).first()
    if quote is None:
        return None, "QUOTE_NOT_FOUND"
    if not (getattr(actor, "is_superuser", False) or can_view_quote_costs_for(actor, quote)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE"
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None, "NO_SELLER_COMPANY"
    items = [it for it in quote.items.all() if it.product_id]
    pricing_by_product = suggest_pricing_for_products([it.product_id for it in items], company_id)
    suggestions = [
        {"item_id": it.id, **pricing_by_product[it.product_id]} for it in items if it.product_id in pricing_by_product
    ]
    return {"suggestions": suggestions}, None
