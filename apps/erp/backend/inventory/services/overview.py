"""Чтение склада для экрана «Склад» (D2-2): остатки с резервами и ожидаемым приходом, карточка товара, резервы, отгрузки.

Только чтение; правила и операции — `inventory.services.stock`, заказы поставщикам — `supply.services.orders`. Приход по
заказам считается по строкам отправленных и подтверждённых заказов (`quantity − received_quantity`), черновик приход не
обещает.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from django.db.models import F, Q
from inventory.access import can_manage_fulfillment, can_manage_supply, person_name, require_staff
from inventory.models import Reservation, Shipment, StockBalance, StockMovement
from inventory.services import stock

from catalog.models import Product

MAX_ROWS = 300
MAX_MOVEMENTS = 30


def rights(user) -> dict:
    return {"manage": can_manage_supply(user), "ship": can_manage_fulfillment(user)}


def _deal_ref(deal) -> Optional[dict]:
    if deal is None:
        return None
    return {"id": deal.pk, "number": deal.number or None, "client_name": deal.company.name if deal.company_id else None}


def _incoming(product_ids: Iterable[int]) -> dict[int, dict]:
    """Ожидаемый приход по товарам: сколько ещё не принято по отправленным и подтверждённым заказам и ближайшая дата."""
    from supply.models import OrderStatus, SupplierOrderLine

    ids = [pid for pid in set(product_ids) if pid]
    found: dict[int, dict] = {}
    if not ids:
        return found
    lines = SupplierOrderLine.objects.filter(
        product_id__in=ids, order__status__in=(OrderStatus.SENT, OrderStatus.CONFIRMED)
    ).select_related("order")
    for line in lines:
        left = line.quantity - line.received_quantity
        if left <= 0:
            continue
        info = found.setdefault(line.product_id, {"quantity": 0, "next_expected": None})
        info["quantity"] += left
        date = line.order.expected_date
        if date is not None and (info["next_expected"] is None or date < info["next_expected"]):
            info["next_expected"] = date
    return found


def _unit(product: Product) -> str:
    return product.uom.name if product.uom_id else ""


def _row(product: Product, state: stock.Availability, incoming: Optional[dict]) -> dict:
    return {
        "product_id": product.pk,
        "name": product.name,
        "article": product.manufacturer_part_number or product.sku or "",
        "unit": _unit(product),
        "on_hand": state.on_hand,
        "reserved": state.reserved,
        "free": state.free,
        "incoming": incoming["quantity"] if incoming else 0,
        "next_expected": incoming["next_expected"].isoformat() if incoming and incoming["next_expected"] else None,
        "cells": [{"cell": cell or None, "on_hand": quantity} for cell, quantity in state.cells if quantity > 0],
    }


def balances(user, *, q: str = "", only: str = "") -> dict:
    """Остатки и резервы по номенклатуре. Попадают товары с остатком, резервом или ожидаемым приходом (и найденные по
    запросу). `only=reserved` — только с резервом; `only=incoming` — только с ожидаемым приходом."""
    require_staff(user)
    from supply.models import OrderStatus, SupplierOrderLine

    live = set(stock.active_reservations().values_list("product_id", flat=True))
    stocked = set(StockBalance.objects.filter(on_hand__gt=0).values_list("product_id", flat=True))
    coming = set(
        SupplierOrderLine.objects.filter(order__status__in=(OrderStatus.SENT, OrderStatus.CONFIRMED))
        .filter(received_quantity__lt=F("quantity"))
        .values_list("product_id", flat=True)
    )
    coming.discard(None)
    if only == "reserved":
        ids = live
    elif only == "incoming":
        ids = coming
    else:
        ids = live | stocked | coming
    products = Product.objects.select_related("uom").exclude(domain_type__code="SERVICES")
    if q:
        # Поиск идёт по всей номенклатуре: товар без остатка находится, чтобы его можно было оприходовать.
        for word in [w for w in q.split() if w][:6]:
            products = products.filter(
                Q(name__icontains=word) | Q(sku__icontains=word) | Q(manufacturer_part_number__icontains=word)
            )
        if only:
            products = products.filter(pk__in=ids)
    else:
        products = products.filter(pk__in=ids)
    products = list(products.order_by("name")[:MAX_ROWS])
    pids = [p.pk for p in products]
    states = stock.availability(pids)
    coming_info = _incoming(pids)
    return {
        "results": [_row(p, states[p.pk], coming_info.get(p.pk)) for p in products],
        "rights": rights(user),
    }


def present_reservation(r: Reservation) -> dict:
    return {
        "id": r.pk,
        "product_id": r.product_id,
        "product_name": r.product.name,
        "deal": _deal_ref(r.deal),
        "quote_item_id": r.quote_item_id,
        "quantity": r.quantity,
        "shipped_quantity": r.shipped_quantity,
        "remaining": r.remaining,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "created_by_name": person_name(r.created_by) if r.created_by_id else None,
    }


def reservations(
    user, *, deal_id: Optional[int] = None, product_id: Optional[int] = None, status: str = "active"
) -> list[dict]:
    require_staff(user)
    qs = Reservation.objects.select_related("product", "deal__company", "created_by")
    if status == "active":
        qs = stock.active_reservations().select_related("product", "deal__company", "created_by")
    elif status:
        qs = qs.filter(status=status)
    if deal_id:
        qs = qs.filter(deal_id=deal_id)
    if product_id:
        qs = qs.filter(product_id=product_id)
    return [present_reservation(r) for r in qs.order_by("deal_id", "id")[:MAX_ROWS]]


def product_detail(user, product_id: int) -> dict:
    from supply.models import OrderStatus, SupplierOrderLine

    require_staff(user)
    product = Product.objects.select_related("uom").filter(pk=product_id).first()
    if product is None:
        raise stock.StockError("PRODUCT_NOT_FOUND", 404)
    state = stock.availability([product.pk])[product.pk]
    incoming = _incoming([product.pk]).get(product.pk)
    lines = (
        SupplierOrderLine.objects.filter(product=product, order__status__in=(OrderStatus.SENT, OrderStatus.CONFIRMED))
        .filter(received_quantity__lt=F("quantity"))
        .select_related("order__supplier")
        .order_by("order__expected_date", "id")
    )
    movements = StockMovement.objects.filter(product=product).select_related("created_by")[:MAX_MOVEMENTS]
    return {
        **_row(product, state, incoming),
        "reservations": reservations(user, product_id=product.pk),
        "incoming_orders": [
            {
                "order_id": line.order_id,
                "number": line.order.number,
                "status": line.order.status,
                "supplier_name": line.order.supplier.name,
                "expected_date": line.order.expected_date.isoformat() if line.order.expected_date else None,
                "quantity_left": line.quantity - line.received_quantity,
            }
            for line in lines
        ],
        "movements": [
            {
                "kind": m.kind,
                "quantity": m.quantity,
                "cell": m.cell or None,
                "at": m.created_at.isoformat(),
                "by_name": person_name(m.created_by) if m.created_by_id else None,
                "note": m.note or None,
            }
            for m in movements
        ],
        "rights": rights(user),
    }


def present_shipment(shipment: Shipment) -> dict:
    return {
        "id": shipment.pk,
        "number": shipment.number,
        "deal": _deal_ref(shipment.deal),
        "tracking": shipment.tracking or None,
        "carrier": shipment.carrier or None,
        "note": shipment.note or None,
        "shipped_at": shipment.shipped_at.isoformat(),
        "shipped_by_name": person_name(shipment.shipped_by) if shipment.shipped_by_id else None,
        "lines": [
            {
                "product_id": line.product_id,
                "name": line.product.name,
                "quantity": line.quantity,
                "cell": line.cell or None,
            }
            for line in shipment.lines.all()
        ],
    }


def shipments(user, *, deal_id: Optional[int] = None) -> dict:
    require_staff(user)
    qs = Shipment.objects.select_related("deal__company", "shipped_by").prefetch_related("lines__product")
    if deal_id:
        qs = qs.filter(deal_id=deal_id)
    return {"results": [present_shipment(s) for s in qs[:MAX_ROWS]], "rights": rights(user)}


def pending_receipts(user) -> dict:
    """«Приёмка»: строки подтверждённых заказов, которые ещё ждут товара, и последние приёмки."""
    from supply.models import GoodsReceipt, OrderStatus, SupplierOrderLine
    from supply.services.orders import is_overdue

    require_staff(user)
    lines = (
        SupplierOrderLine.objects.filter(order__status=OrderStatus.CONFIRMED, received_quantity__lt=F("quantity"))
        .select_related("order__supplier", "deal__company")
        .order_by("order__expected_date", "order_id", "position")[:MAX_ROWS]
    )
    receipts = GoodsReceipt.objects.select_related("order__supplier", "received_by").prefetch_related(
        "lines__order_line"
    )[:50]
    return {
        "pending": [
            {
                "order_id": line.order_id,
                "order_number": line.order.number,
                "supplier_name": line.order.supplier.name,
                "expected_date": line.order.expected_date.isoformat() if line.order.expected_date else None,
                "overdue": is_overdue(line.order),
                "order_line_id": line.pk,
                "name": line.name,
                "article": line.article,
                "unit": line.unit,
                "quantity": line.quantity,
                "received_quantity": line.received_quantity,
                "deal": _deal_ref(line.deal),
            }
            for line in lines
        ],
        "done": [
            {
                "id": receipt.pk,
                "order_id": receipt.order_id,
                "order_number": receipt.order.number,
                "supplier_name": receipt.order.supplier.name,
                "received_at": receipt.received_at.isoformat(),
                "received_by_name": person_name(receipt.received_by) if receipt.received_by_id else None,
                "supplier_doc": receipt.supplier_doc or None,
                "quantity": sum(rl.quantity for rl in receipt.lines.all()),
                "lines": [
                    {"name": rl.order_line.name, "quantity": rl.quantity, "cell": rl.cell or None}
                    for rl in receipt.lines.all()
                ],
            }
            for receipt in receipts
        ],
        "rights": rights(user),
    }


def suppliers(user, q: str = "") -> list[dict]:
    """Внешние поставщики для выбора в запросе цены и заказе (D2-3 ведёт справочник; здесь — только выбор)."""
    from parties.models import Company
    from supply.services.orders import supplier_email

    from core.tenant import own_company_id

    require_staff(user)
    qs = Company.objects.sellers().exclude(pk=own_company_id() or 0)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(inn__icontains=q))
    rows: list[dict[str, Any]] = []
    for company in qs.order_by("name")[:50]:
        email = supplier_email(company)
        rows.append({"id": company.pk, "name": company.name, "inn": company.inn or None, "email": email or None})
    return rows


__all__ = [
    "balances",
    "pending_receipts",
    "present_shipment",
    "product_detail",
    "reservations",
    "shipments",
    "suppliers",
]
