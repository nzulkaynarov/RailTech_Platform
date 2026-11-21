"""Shortage of a project's goods: the ONE formula behind «Create order · For the request shortage» and the supply task.

For a goods line of a quote (a catalog card, not a service, quantity above zero) the shortage is

    quantity − shipped − what the active reservation still holds − ordered and not yet received (draft, sent, confirmed)

Shipped goods are subtracted: after a shipment the reservation is fulfilled and no longer counts, so without the
`shipped` term the already delivered quantity would be ordered again.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from django.db.models import Sum
from inventory.models import ShipmentLine
from inventory.services import stock
from supply.models import OrderStatus, SupplierOrderLine

#: Orders whose not yet received remainder still counts as «ordered».
LIVE_STATUSES = (OrderStatus.DRAFT, OrderStatus.SENT, OrderStatus.CONFIRMED)


def ordered_by_item(item_ids) -> dict[int, Decimal]:
    """Quote lines → quantity already ordered and not yet received in live orders."""
    ids = [i for i in set(item_ids) if i]
    if not ids:
        return {}
    rows = (
        SupplierOrderLine.objects.filter(quote_item_id__in=ids, order__status__in=LIVE_STATUSES)
        .values("quote_item_id")
        .annotate(total=Sum("quantity") - Sum("received_quantity"))
    )
    return {row["quote_item_id"]: max(row["total"] or 0, 0) for row in rows}


def shipped_by_item(item_ids) -> dict[int, Decimal]:
    ids = [i for i in set(item_ids) if i]
    if not ids:
        return {}
    rows = ShipmentLine.objects.filter(quote_item_id__in=ids).values("quote_item_id").annotate(total=Sum("quantity"))
    return {row["quote_item_id"]: row["total"] or 0 for row in rows}


def goods_items(quote_ids: Iterable[int]) -> dict[int, list]:
    """Quote id → its goods lines that stock tracks: payable, with a catalog card, not a service, quantity above zero.
    One query for all quotes."""
    from sales.models import QuoteItem

    from crm.services.calculation import zone_of

    result: dict[int, list] = defaultdict(list)
    items = (
        QuoteItem.objects.filter(quote_id__in=list(quote_ids))
        .billable()
        .select_related("product__domain_type", "calc")
        .order_by("quote_id", "position", "id")
    )
    for item in items:
        if item.product_id and not item.product.is_service and zone_of(item) == "goods" and item.quantity > 0:
            result[item.quote_id].append(item)
    return result


def shortage_by_item(items: list) -> dict[int, Decimal]:
    """Quote line id → missing quantity (only lines with a positive shortage). Three aggregate queries for any number
    of lines."""
    ids = [item.pk for item in items]
    reserved = stock.reserved_by_item(ids)
    shipped = shipped_by_item(ids)
    ordered = ordered_by_item(ids)
    missing = {
        item.pk: item.quantity - shipped.get(item.pk, 0) - reserved.get(item.pk, 0) - ordered.get(item.pk, 0)
        for item in items
    }
    return {pk: qty for pk, qty in missing.items() if qty > 0}
