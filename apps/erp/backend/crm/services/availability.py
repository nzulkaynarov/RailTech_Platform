"""ATP (available-to-promise) auto-split of КП lines by seller stock.

Owner directive (Track B): the delivery срок of an in-stock quantity must come from the
catalog (the seller's own SupplierOffer), and a line whose requested quantity exceeds the
складской остаток must split into two tranches — what ships from stock fast, and the
remainder that goes под заказ. Automated so a КП of hundreds of lines needs no per-line
clicks. This module is the pure split rule; the seller-side trigger lives in quotes.py.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from django.db import transaction


@dataclass(frozen=True)
class Tranche:
    """One delivery tranche of a line: `quantity` units promised at `lead_time_days`."""

    quantity: int
    lead_time_days: int


def split_line_by_availability(product, requested_qty: int, offer) -> List[Tranche]:
    """Split `requested_qty` of `product` into delivery tranches by the seller `offer`'s stock.

    Rules (owner spec):
      * offer.stock_quantity > 0 AND requested_qty > stock_quantity → TWO tranches:
          1. stock_quantity units @ in_stock_lead_time_days  (наличие)
          2. (requested_qty − stock_quantity) units @ order_lead_time_days  (под заказ)
      * otherwise ONE tranche:
          - requested_qty @ in_stock_lead_time_days  when the order fits the stock
            (offer.stock_quantity >= requested_qty AND stock_quantity > 0)
          - requested_qty @ order_lead_time_days  otherwise (incl. zero/None stock)
      * no offer → ONE tranche: requested_qty @ 0 (no catalog срок to promise).

    `product` is accepted for signature stability / future per-product rules; the split is
    driven entirely by the offer. Returns a list of Tranche (always ≥1, never empty for
    requested_qty ≥ 1).
    """
    requested = int(requested_qty or 0)
    if requested < 1:
        return []

    if offer is None:
        return [Tranche(quantity=requested, lead_time_days=0)]

    stock = int(offer.stock_quantity or 0)
    in_stock_days = int(offer.in_stock_lead_time_days or 0)
    order_days = int(offer.order_lead_time_days or 0)

    if stock > 0 and requested > stock:
        return [
            Tranche(quantity=stock, lead_time_days=in_stock_days),
            Tranche(quantity=requested - stock, lead_time_days=order_days),
        ]

    fits_stock = stock > 0 and requested <= stock
    return [Tranche(quantity=requested, lead_time_days=in_stock_days if fits_stock else order_days)]


def resolve_seller_offer(product, seller_company_id: Optional[int]):
    """The seller's OWN active offer for `product` (the source of catalog lead times).

    Scoped to the company that owns the КП — a seller prices off its own stock/срок, never
    another supplier's offer. Returns the SupplierOffer or None (no offer / unknown seller).
    """
    if not (product and seller_company_id):
        return None
    from catalog.models import SupplierOffer

    return (
        SupplierOffer.objects.filter(product=product, supplier_id=seller_company_id, is_active=True)
        .order_by("base_price")
        .first()
    )


@transaction.atomic
def auto_split_quote_by_availability(quote, seller_company_id: Optional[int]) -> int:
    """Replace each product-linked КП line with its availability tranches, in bulk.

    For hundreds of lines the seller can't split by hand — this runs once over the whole
    КП. For every line that links a Product whose seller offer implies a split (requested
    qty exceeds the складской остаток), the single line is replaced by its tranches: same
    product, frozen base price, cost currency, spec — only quantity + lead_time_days differ
    per tranche.

    Idempotency: a line is skipped when it is ALREADY a tranche of a split — detected by the
    presence of more than one line for the same (product, offer) on this КП. So re-running
    after a split is a no-op. Frozen КП are never touched. Returns the number of NEW tranche
    lines created (0 when nothing split).

    `seller_company_id` scopes which offer (the КП-owning seller's own) drives the split.
    """
    from ..models import QuoteItem

    if quote.frozen_at:
        return 0

    lines = list(quote.items.select_related("product").all())
    # Lines already belonging to a multi-line product group are treated as a finished split.
    product_line_count: dict = {}
    for line in lines:
        if line.product_id:
            product_line_count[line.product_id] = product_line_count.get(line.product_id, 0) + 1

    created_total = 0
    for line in lines:
        if not line.product_id or line.frozen_base_price is None:
            continue
        # Already split (>1 line for this product) → leave the group alone (idempotent).
        if product_line_count.get(line.product_id, 0) > 1:
            continue
        offer = resolve_seller_offer(line.product, seller_company_id)
        if offer is None:
            continue
        tranches = split_line_by_availability(line.product, line.quantity, offer)
        if len(tranches) <= 1:
            continue
        # First tranche reuses the existing line (keep its pk / history); the rest are clones.
        first, *rest = tranches
        line.quantity = first.quantity
        line.lead_time_days = first.lead_time_days
        line.save(update_fields=["quantity", "lead_time_days"])
        new_lines = [_clone_tranche(line, tranche) for tranche in rest]
        QuoteItem.objects.bulk_create(new_lines)
        created_total += len(new_lines)

    if created_total:
        quote.recalculate_totals()
    return created_total


def _clone_tranche(source, tranche: Tranche):
    """A new QuoteItem identical to `source` but carrying one tranche's qty + lead time.

    Clones the spec + frozen price snapshot so each tranche prices identically; only the
    quantity and the срок differ. pk/created fields are left unset for bulk_create.
    """
    from ..models import QuoteItem

    return QuoteItem(
        quote_id=source.quote_id,
        product_id=source.product_id,
        offer_id=source.offer_id,
        # Inherit the source line's row order so tranche clones stay grouped with it (default 0
        # would otherwise float every clone to the top of a positioned КП).
        position=source.position,
        display_type=source.display_type,
        is_optional=source.is_optional,
        imported_raw_name=source.imported_raw_name,
        name_canonical=source.name_canonical,
        unit=source.unit,
        unit_code=source.unit_code,
        mpn=source.mpn,
        gost_drawing=source.gost_drawing,
        hs_code=source.hs_code,
        note=source.note,
        assigned_at=source.assigned_at,
        frozen_base_price=source.frozen_base_price if source.frozen_base_price is not None else Decimal("0"),
        frozen_currency_id=source.frozen_currency_id,
        logistics_cost=source.logistics_cost,
        customs_duty=source.customs_duty,
        margin_percent=source.margin_percent,
        discount_percent=source.discount_percent,
        quantity=tranche.quantity,
        lead_time_days=tranche.lead_time_days,
    )
