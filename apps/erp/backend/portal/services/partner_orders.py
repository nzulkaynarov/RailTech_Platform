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
