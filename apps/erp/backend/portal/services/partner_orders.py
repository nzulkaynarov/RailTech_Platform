"""Операции партнёра с заказами на поставку и запросами цен (K2-orders, ADR-0022).

Партнёр видит только свои заказы поставщику (`SupplierOrder`) и запросы цен (`PriceRequest`).
Все операции доступны сессии с модулем `my_products`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from portal.exceptions import PortalConflict
from supply.models import OrderLogKind, OrderStatus, PriceRequest, PriceRequestStatus, SupplierOrder, SupplierOrderLog

ORDER_STATUSES = set(OrderStatus.values)
PRICE_REQUEST_STATUSES = {"sent", "answered"}


def _custom_user_or_none(user):
    User = get_user_model()
    return user if isinstance(user, User) else None


def _format_money(value: Any) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def list_partner_orders(
    company,
    status: Optional[str] = None,
    q: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base_qs = SupplierOrder.objects.filter(supplier=company)
    counts = {
        "all": base_qs.count(),
        "sent": base_qs.filter(status=OrderStatus.SENT).count(),
        "confirmed": base_qs.filter(status=OrderStatus.CONFIRMED).count(),
        "received": base_qs.filter(status=OrderStatus.RECEIVED).count(),
        "cancelled": base_qs.filter(status=OrderStatus.CANCELLED).count(),
    }

    qs = base_qs
    if status:
        qs = qs.filter(status=status)
    if q.strip():
        term = q.strip()
        qs = qs.filter(
            Q(number__icontains=term) | Q(lines__name__icontains=term) | Q(lines__article__icontains=term)
        ).distinct()

    qs = qs.order_by("-created_at", "-id")
    total = qs.count()
    start = (page - 1) * page_size
    orders = list(qs.select_related("currency").prefetch_related("lines")[start : start + page_size])

    items = []
    for order in orders:
        lines = list(order.lines.all())
        total_amount = sum((line.unit_price or Decimal("0.00")) * line.quantity for line in lines)
        items.append(
            {
                "id": order.id,
                "number": order.number,
                "status": order.status,
                "expected_date": order.expected_date,
                "created_at": order.created_at,
                "sent_at": order.sent_at,
                "confirmed_at": order.confirmed_at,
                "received_at": order.received_at,
                "cancelled_at": order.cancelled_at,
                "lines_count": len(lines),
                "total_amount": _format_money(total_amount),
                "currency": order.currency.code if order.currency else "RUB",
            }
        )

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "counts": counts,
    }


def get_partner_order(company, order_id: int) -> Optional[dict]:
    order = (
        SupplierOrder.objects.filter(supplier=company, pk=order_id)
        .select_related("currency")
        .prefetch_related("lines", "log")
        .first()
    )
    if order is None:
        return None

    lines = []
    total_amount = Decimal("0.00")
    for line in order.lines.all().order_by("position", "id"):
        unit_p = line.unit_price or Decimal("0.00")
        tot_p = unit_p * line.quantity
        total_amount += tot_p
        lines.append(
            {
                "id": line.id,
                "position": line.position,
                "product_id": line.product_id,
                "name": line.name,
                "article": line.article or "",
                "unit": line.unit or "",
                "quantity": line.quantity,
                "received_quantity": line.received_quantity,
                "unit_price": _format_money(unit_p),
                "total_price": _format_money(tot_p),
            }
        )

    logs = [
        {
            "id": log.id,
            "kind": log.kind,
            "detail": log.detail or "",
            "created_at": log.created_at,
        }
        for log in order.log.all().order_by("created_at", "id")
    ]

    receipts = []
    for receipt in (
        order.receipts.all().prefetch_related("lines__order_line", "lines__warehouse").order_by("-received_at", "-id")
    ):
        rlines = []
        for rline in receipt.lines.all().order_by("id"):
            rlines.append(
                {
                    "id": rline.id,
                    "order_line_id": rline.order_line_id,
                    "name": rline.order_line.name if rline.order_line else "",
                    "article": (rline.order_line.article if rline.order_line else "") or "",
                    "quantity": rline.quantity,
                    "unit": (rline.order_line.unit if rline.order_line else "") or "",
                    "warehouse_name": rline.warehouse.name if rline.warehouse else "",
                    "conformity_doc_number": rline.conformity_doc_number or "",
                    "conformity_doc_valid_until": rline.conformity_doc_valid_until,
                }
            )
        receipts.append(
            {
                "id": receipt.id,
                "supplier_doc": receipt.supplier_doc or "",
                "note": receipt.note or "",
                "received_at": receipt.received_at,
                "lines": rlines,
            }
        )

    return {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "expected_date": order.expected_date,
        "created_at": order.created_at,
        "sent_at": order.sent_at,
        "confirmed_at": order.confirmed_at,
        "received_at": order.received_at,
        "cancelled_at": order.cancelled_at,
        "cancel_reason": order.cancel_reason or "",
        "note": order.note or "",
        "total_amount": _format_money(total_amount),
        "currency": order.currency.code if order.currency else "RUB",
        "lines": lines,
        "logs": logs,
        "receipts": receipts,
    }


@transaction.atomic
def confirm_partner_order(company, user, order_id: int, expected_date=None) -> Optional[dict]:
    order = SupplierOrder.objects.select_for_update().filter(supplier=company, pk=order_id).first()
    if order is None:
        return None
    if order.status not in (OrderStatus.SENT, OrderStatus.DRAFT, OrderStatus.CONFIRMED):
        raise PortalConflict("ORDER_FINALIZED")

    if expected_date is not None:
        order.expected_date = expected_date
    order.status = OrderStatus.CONFIRMED
    order.confirmed_at = timezone.now()
    order.confirmed_by = _custom_user_or_none(user)
    order.save(update_fields=["status", "confirmed_at", "confirmed_by", "expected_date", "updated_at"])

    actor_name = getattr(user, "name", str(user)) if user else ""
    actor_part = f" ({actor_name})" if actor_name else ""
    SupplierOrderLog.objects.create(
        order=order,
        kind=OrderLogKind.CONFIRMED,
        user=_custom_user_or_none(user),
        detail=f"Подтверждён поставщиком{actor_part}"
        + (f", ожидаемая дата: {order.expected_date}" if order.expected_date else ""),
    )
    return get_partner_order(company, order.pk)


@transaction.atomic
def ship_partner_order(
    company, user, order_id: int, supplier_doc: str, carrier: str = "", tracking_number: str = "", note: str = ""
) -> Optional[dict]:
    order = SupplierOrder.objects.select_for_update().filter(supplier=company, pk=order_id).first()
    if order is None:
        return None
    if order.status == OrderStatus.CANCELLED:
        raise PortalConflict("ORDER_FINALIZED")

    detail_parts = [f"Накладная: {supplier_doc}"]
    if carrier:
        detail_parts.append(f"Перевозчик: {carrier}")
    if tracking_number:
        detail_parts.append(f"Трек: {tracking_number}")
    if note:
        detail_parts.append(note)
    actor_name = getattr(user, "name", str(user)) if user else ""
    actor_part = f" ({actor_name})" if actor_name else ""
    detail = f"Уведомление об отгрузке{actor_part}: " + "; ".join(detail_parts)

    SupplierOrderLog.objects.create(
        order=order,
        kind=OrderLogKind.EDITED,
        user=_custom_user_or_none(user),
        detail=detail[:500],
    )
    order.save(update_fields=["updated_at"])
    return get_partner_order(company, order.pk)


def list_partner_price_requests(
    company,
    status: Optional[str] = None,
    q: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base_qs = PriceRequest.objects.filter(supplier=company)
    counts = {
        "all": base_qs.count(),
        "sent": base_qs.filter(answered_at__isnull=True, status=PriceRequestStatus.SENT).count(),
        "answered": base_qs.filter(answered_at__isnull=False).count(),
    }

    qs = base_qs
    if status == "answered":
        qs = qs.filter(answered_at__isnull=False)
    elif status == "sent":
        qs = qs.filter(answered_at__isnull=True, status=PriceRequestStatus.SENT)

    if q.strip():
        term = q.strip()
        qs = qs.filter(Q(subject__icontains=term) | Q(note__icontains=term) | Q(lines__name__icontains=term)).distinct()

    qs = qs.order_by("-requested_at", "-id")
    total = qs.count()
    start = (page - 1) * page_size
    requests = list(qs.prefetch_related("lines")[start : start + page_size])

    items = [
        {
            "id": req.id,
            "requested_at": req.requested_at,
            "subject": req.subject,
            "status": "answered" if req.answered_at else req.status,
            "lines_count": req.lines.count(),
            "answered_at": req.answered_at,
        }
        for req in requests
    ]

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "counts": counts,
    }


def get_partner_price_request(company, request_id: int) -> Optional[dict]:
    req = PriceRequest.objects.filter(supplier=company, pk=request_id).prefetch_related("lines").first()
    if req is None:
        return None

    lines = [
        {
            "id": line.id,
            "name": line.name,
            "article": line.article or "",
            "quantity": line.quantity,
            "unit": line.unit or "",
        }
        for line in req.lines.all().order_by("id")
    ]

    return {
        "id": req.id,
        "requested_at": req.requested_at,
        "subject": req.subject,
        "note": req.note or "",
        "status": "answered" if req.answered_at else req.status,
        "answered_at": req.answered_at,
        "answer_note": req.answer_note or "",
        "lines": lines,
    }


@transaction.atomic
def respond_partner_price_request(company, user, request_id: int, answer_note: str) -> Optional[dict]:
    req = PriceRequest.objects.select_for_update().filter(supplier=company, pk=request_id).first()
    if req is None:
        return None

    req.answered_at = timezone.now()
    req.answered_by = _custom_user_or_none(user)
    req.answer_note = answer_note.strip()[:1000]
    req.save(update_fields=["answered_at", "answered_by", "answer_note"])
    return get_partner_price_request(company, req.pk)


def get_partner_finance_summary(company) -> dict:
    from portal.services.partner_products import offers_attention

    from catalog.models import SupplierOffer

    orders_qs = (
        SupplierOrder.objects.filter(supplier=company)
        .select_related("currency")
        .prefetch_related("lines", "receipts")
        .order_by("-created_at", "-id")
    )
    all_orders = list(orders_qs)

    currency_map: dict[str, dict] = {}
    settlement_lines = []

    for order in all_orders:
        lines = list(order.lines.all())
        curr = order.currency.code if order.currency else "RUB"

        ordered_amount = sum(((line.unit_price or Decimal("0.00")) * line.quantity for line in lines), Decimal("0.00"))
        received_amount = sum(
            ((line.unit_price or Decimal("0.00")) * line.received_quantity for line in lines), Decimal("0.00")
        )

        if order.status in (OrderStatus.SENT, OrderStatus.CONFIRMED):
            in_transit_amount = sum(
                (
                    (line.unit_price or Decimal("0.00")) * max(0, line.quantity - line.received_quantity)
                    for line in lines
                ),
                Decimal("0.00"),
            )
        else:
            in_transit_amount = Decimal("0.00")

        settlement_lines.append(
            {
                "order_id": order.id,
                "order_number": order.number,
                "order_date": order.created_at,
                "status": order.status,
                "currency": curr,
                "ordered_amount": _format_money(ordered_amount),
                "received_amount": _format_money(received_amount),
                "in_transit_amount": _format_money(in_transit_amount),
                "receipts_count": order.receipts.count(),
            }
        )

        if order.status != OrderStatus.CANCELLED:
            if curr not in currency_map:
                currency_map[curr] = {
                    "currency": curr,
                    "ordered_total": Decimal("0.00"),
                    "received_total": Decimal("0.00"),
                    "in_transit_total": Decimal("0.00"),
                    "orders_count": 0,
                }
            c_entry = currency_map[curr]
            c_entry["ordered_total"] += ordered_amount
            c_entry["received_total"] += received_amount
            c_entry["in_transit_total"] += in_transit_amount
            c_entry["orders_count"] += 1

    balances = [
        {
            "currency": c["currency"],
            "ordered_total": _format_money(c["ordered_total"]),
            "received_total": _format_money(c["received_total"]),
            "in_transit_total": _format_money(c["in_transit_total"]),
            "orders_count": c["orders_count"],
        }
        for c in sorted(currency_map.values(), key=lambda x: x["currency"])
    ]

    # Scorecard: OTIF
    completed_orders = [o for o in all_orders if o.status == OrderStatus.RECEIVED]
    otif_count = 0
    for order in completed_orders:
        lines = list(order.lines.all())
        in_full = all(line.received_quantity >= line.quantity for line in lines)
        if not in_full:
            continue
        if order.expected_date:
            order_date = order.received_at.date() if order.received_at else None
            if not order_date:
                latest_receipt = order.receipts.order_by("-received_at").first()
                if latest_receipt:
                    order_date = latest_receipt.received_at.date()
            if order_date and order_date > order.expected_date:
                continue
        otif_count += 1

    completed_orders_count = len(completed_orders)
    otif_rate = round((otif_count / completed_orders_count * 100), 1) if completed_orders_count > 0 else 100.0

    # Scorecard: RFQ response rate
    rfqs = PriceRequest.objects.filter(supplier=company)
    total_rfqs_count = rfqs.count()
    answered_rfqs = rfqs.filter(answered_at__isnull=False).count()
    rfq_response_rate = round((answered_rfqs / total_rfqs_count * 100), 1) if total_rfqs_count > 0 else 100.0

    # Scorecard: Price freshness rate
    active_offers = SupplierOffer.objects.filter(supplier=company, is_active=True)
    active_offers_count = active_offers.count()
    if active_offers_count > 0:
        totals = offers_attention(company)
        expired = totals.get("expired") or 0
        stale = totals.get("stale") or 0
        fresh_count = max(0, active_offers_count - expired - stale)
        price_freshness_rate = round((fresh_count / active_offers_count * 100), 1)
    else:
        price_freshness_rate = 100.0

    scorecard = {
        "otif_rate": otif_rate,
        "rfq_response_rate": rfq_response_rate,
        "price_freshness_rate": price_freshness_rate,
        "completed_orders_count": completed_orders_count,
        "total_rfqs_count": total_rfqs_count,
        "active_offers_count": active_offers_count,
    }

    return {
        "balances": balances,
        "scorecard": scorecard,
        "settlements": settlement_lines,
    }
