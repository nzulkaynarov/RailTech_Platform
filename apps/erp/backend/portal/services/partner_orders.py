"""Операции партнёра с заказами на поставку и запросами цен (K2-orders, ADR-0022; правила — FX-7).

Партнёр видит только свои заказы поставщику (`SupplierOrder`) и запросы цен (`PriceRequest`), без черновиков и внутренних
заметок. Все операции доступны сессии с модулем `my_products`.

* Подтвердить можно только заказ `sent` (как `TRANSITIONS`), дата обязательна.
* Срок `expected_date` у заказа, где он уже есть, партнёр не меняет: другая дата — запрос на перенос; решает сотрудник.
* Уведомление об отгрузке — только по `confirmed`, одна накладная на заказ — один раз.
* Ответ на запрос цен — один раз; цены ответа обновляют цену поставщика (`rfq_reply`), но не строку расчёта.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pghistory
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from portal.exceptions import PortalConflict, PortalValidationError
from supply.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    OrderLogKind,
    OrderStatus,
    PriceRequest,
    PriceRequestLine,
    PriceRequestStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderLog,
    SupplierOrderShipmentNotice,
)

logger = logging.getLogger(__name__)

ORDER_STATUSES = set(OrderStatus.values)
PRICE_REQUEST_STATUSES = {"sent", "answered", "failed"}

#: События журнала, которые партнёр видит; остальное (создание, правки, просрочка) — внутренняя работа снабжения.
PARTNER_LOG_KINDS = (
    OrderLogKind.SENT,
    OrderLogKind.CONFIRMED,
    OrderLogKind.RECEIPT,
    OrderLogKind.RECEIVED,
    OrderLogKind.CANCELLED,
)

EVENT_CONFIRMED = "supplier_order.partner_confirmed"
EVENT_DATE_CHANGE = "supplier_order.partner_date_change"
EVENT_SHIPPED = "supplier_order.partner_shipped"
EVENT_RFQ_ANSWERED = "rfq.partner_answered"


def _visible_orders(company):
    """Заказы партнёра: черновик — наша внутренняя работа, поставщику он не отправлен."""
    return SupplierOrder.objects.filter(supplier=company).exclude(status=OrderStatus.DRAFT)


def _custom_user_or_none(user):
    User = get_user_model()
    return user if isinstance(user, User) else None


def _format_money(value: Any) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def _actor_part(user) -> str:
    actor_name = getattr(user, "name", str(user)) if user else ""
    return f" ({actor_name})" if actor_name else ""


def _supply_recipients(company, author) -> list:
    """Кому сообщить: автор заказа или запроса и ответственный по отношению; никого — все с правом `supply.manage`."""
    from accounts.constants import Permission
    from accounts.models import CustomUser
    from core.tenant import own_company_id
    from parties.models import CompanyRelationship, RelationshipRole

    relationship = (
        CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER)
        .select_related("responsible")
        .first()
    )
    people = {
        user.pk: user for user in (author, relationship.responsible if relationship else None) if user is not None
    }
    active = [user for user in people.values() if user.is_active]
    if active:
        return active
    return list(
        CustomUser.objects.filter(
            is_active=True,
            memberships__company_id=own_company_id(),
            memberships__is_active=True,
            memberships__company_roles__permissions__contains=[Permission.SUPPLY_MANAGE.value],
        ).distinct()
    )


def _notify_supply(company, author, *, title: str, message: str, event_code: str, params: dict, deal=None) -> None:
    """Уведомление снабжению после фиксации действия: его сбой не отменяет действие партнёра."""
    from notifications.services import notify_platform_admins, notify_user

    try:
        recipients = _supply_recipients(company, author)
        if not recipients:
            notify_platform_admins(
                title=title, message=message, type_code="INFO", event_code=event_code, event_params=params
            )
            return
        for user in recipients:
            notify_user(
                user=user,
                title=title,
                message=message,
                deal=deal,
                type_code="INFO",
                event_code=event_code,
                event_params=params,
            )
    except Exception:
        logger.exception("Не удалось уведомить снабжение о событии %s", event_code)


def _notify_date_change(order: SupplierOrder) -> None:
    current = order.expected_date.strftime("%d.%m.%Y") if order.expected_date else "не задан"
    wanted = order.partner_requested_date.strftime("%d.%m.%Y")
    _notify_supply(
        order.supplier,
        order.created_by,
        title=f"Партнёр просит перенести срок заказа {order.number}",
        message=f"«{order.supplier.name}»: срок {current}, просит {wanted}. Срок не изменён, решает снабжение.",
        event_code=EVENT_DATE_CHANGE,
        params={"number": order.number, "supplier": order.supplier.name, "requested_date": wanted},
    )


def _record_date_change(order: SupplierOrder, user, requested_date: date, reason: str = "") -> None:
    order.partner_requested_date = requested_date
    order.partner_requested_at = timezone.now()
    order.partner_requested_reason = reason.strip()[:500]
    order.save(
        update_fields=["partner_requested_date", "partner_requested_at", "partner_requested_reason", "updated_at"]
    )
    SupplierOrderLog.objects.create(
        order=order,
        kind=OrderLogKind.EDITED,
        user=_custom_user_or_none(user),
        detail=(
            f"Запрос переноса срока{_actor_part(user)}: {requested_date:%d.%m.%Y}"
            + (f"; {order.partner_requested_reason}" if order.partner_requested_reason else "")
        )[:500],
    )


def _check_date_not_past(value: date) -> None:
    if value < timezone.localdate():
        raise PortalValidationError("VALIDATION_ERROR")


def list_partner_orders(
    company,
    status: Optional[str] = None,
    q: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base_qs = _visible_orders(company)
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
                "currency": order.currency.code if order.currency else None,
            }
        )

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "counts": counts,
    }


def _partner_receipts() -> Prefetch:
    return Prefetch(
        "receipts",
        queryset=GoodsReceipt.objects.order_by("-received_at", "-id").prefetch_related(
            Prefetch(
                "lines",
                queryset=GoodsReceiptLine.objects.order_by("id").select_related("order_line", "warehouse"),
            )
        ),
    )


def get_partner_order(company, order_id: int) -> Optional[dict]:
    order = (
        _visible_orders(company)
        .filter(pk=order_id)
        .select_related("currency")
        .prefetch_related(
            Prefetch("lines", queryset=SupplierOrderLine.objects.order_by("position", "id")),
            Prefetch(
                "log",
                queryset=SupplierOrderLog.objects.filter(kind__in=PARTNER_LOG_KINDS).order_by("created_at", "id"),
            ),
            Prefetch("shipment_notices", queryset=SupplierOrderShipmentNotice.objects.order_by("created_at", "id")),
            _partner_receipts(),
        )
        .first()
    )
    if order is None:
        return None

    lines = []
    total_amount = Decimal("0.00")
    for line in order.lines.all():
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

    # Подробности журнала — внутренние (причина отмены, правки): партнёру только факт и время события.
    logs = [{"id": log.id, "kind": log.kind, "created_at": log.created_at} for log in order.log.all()]

    receipts = []
    for receipt in order.receipts.all():
        rlines = []
        for rline in receipt.lines.all():
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
                "received_at": receipt.received_at,
                "lines": rlines,
            }
        )

    date_change = None
    if order.partner_requested_date is not None:
        date_change = {
            "requested_date": order.partner_requested_date,
            "reason": order.partner_requested_reason or "",
            "requested_at": order.partner_requested_at,
        }

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
        "note": order.note or "",
        "total_amount": _format_money(total_amount),
        "currency": order.currency.code if order.currency else None,
        "date_change": date_change,
        "lines": lines,
        "logs": logs,
        "receipts": receipts,
        "shipment_notices": [
            {
                "id": notice.id,
                "supplier_doc": notice.supplier_doc,
                "carrier": notice.carrier,
                "tracking_number": notice.tracking_number,
                "note": notice.note,
                "created_at": notice.created_at,
            }
            for notice in order.shipment_notices.all()
        ],
    }


def _locked_order(company, order_id: int) -> Optional[SupplierOrder]:
    return (
        _visible_orders(company)
        .select_for_update(of=("self",))
        .select_related("supplier", "created_by")
        .filter(pk=order_id)
        .first()
    )


def confirm_partner_order(company, user, order_id: int, expected_date: date) -> Optional[dict]:
    """Подтвердить заказ `sent` с датой партнёра. Срок уже есть и дата другая — срок не меняется, это запрос на перенос."""
    _check_date_not_past(expected_date)
    with transaction.atomic():
        order = _locked_order(company, order_id)
        if order is None:
            return None
        if order.status != OrderStatus.SENT:
            raise PortalConflict("TRANSITION_NOT_ALLOWED")

        date_differs = order.expected_date is not None and order.expected_date != expected_date
        if order.expected_date is None:
            order.expected_date = expected_date
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = timezone.now()
        order.confirmed_by = _custom_user_or_none(user)
        order.save(update_fields=["status", "confirmed_at", "confirmed_by", "expected_date", "updated_at"])
        SupplierOrderLog.objects.create(
            order=order,
            kind=OrderLogKind.CONFIRMED,
            user=_custom_user_or_none(user),
            detail=f"Подтверждён поставщиком{_actor_part(user)}, дата поставщика: {expected_date:%d.%m.%Y}",
        )
        if date_differs:
            _record_date_change(order, user, expected_date)

    if date_differs:
        _notify_date_change(order)
    else:
        _notify_supply(
            company,
            order.created_by,
            title=f"Партнёр подтвердил заказ {order.number}",
            message=f"«{company.name}»: срок поставки {order.expected_date:%d.%m.%Y}.",
            event_code=EVENT_CONFIRMED,
            params={"number": order.number, "supplier": company.name},
        )
    return get_partner_order(company, order.pk)


def request_partner_date_change(company, user, order_id: int, requested_date: date, reason: str = "") -> Optional[dict]:
    """Запрос на перенос срока подтверждённого заказа. Срок и OTIF не меняются; решение — у снабжения (`update_order`)."""
    with transaction.atomic():
        order = _locked_order(company, order_id)
        if order is None:
            return None
        if order.status != OrderStatus.CONFIRMED:
            raise PortalConflict("ORDER_NOT_CONFIRMED")
        _check_date_not_past(requested_date)
        if requested_date == order.expected_date:
            raise PortalValidationError("VALIDATION_ERROR")
        already_requested = order.partner_requested_date == requested_date
        if not already_requested:
            _record_date_change(order, user, requested_date, reason)

    if not already_requested:
        _notify_date_change(order)
    return get_partner_order(company, order.pk)


def ship_partner_order(
    company, user, order_id: int, supplier_doc: str, carrier: str = "", tracking_number: str = "", note: str = ""
) -> Optional[dict]:
    """Уведомление об отгрузке по подтверждённому заказу; партии — разными накладными, одна накладная — один раз."""
    supplier_doc = supplier_doc.strip()
    with transaction.atomic():
        order = _locked_order(company, order_id)
        if order is None:
            return None
        if order.status != OrderStatus.CONFIRMED:
            raise PortalConflict("ORDER_NOT_CONFIRMED")
        if order.shipment_notices.filter(supplier_doc__iexact=supplier_doc).exists():
            raise PortalConflict("SHIPMENT_NOTICE_DUPLICATE")

        SupplierOrderShipmentNotice.objects.create(
            order=order,
            supplier_doc=supplier_doc,
            carrier=carrier,
            tracking_number=tracking_number,
            note=note,
            contact=user if getattr(user, "company_id", None) else None,
        )
        detail_parts = [f"Накладная: {supplier_doc}"]
        if carrier:
            detail_parts.append(f"Перевозчик: {carrier}")
        if tracking_number:
            detail_parts.append(f"Трек: {tracking_number}")
        if note:
            detail_parts.append(note)
        SupplierOrderLog.objects.create(
            order=order,
            kind=OrderLogKind.EDITED,
            user=_custom_user_or_none(user),
            detail=f"Уведомление об отгрузке{_actor_part(user)}: " + "; ".join(detail_parts),
        )
        order.save(update_fields=["updated_at"])

    _notify_supply(
        company,
        order.created_by,
        title=f"Партнёр отгрузил заказ {order.number}",
        message=f"«{company.name}»: накладная {supplier_doc}."
        + (f" Трек: {tracking_number}." if tracking_number else ""),
        event_code=EVENT_SHIPPED,
        params={"number": order.number, "supplier": company.name, "supplier_doc": supplier_doc},
    )
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
    elif status == "failed":
        qs = qs.filter(answered_at__isnull=True, status=PriceRequestStatus.FAILED)

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
            "lines_count": len(req.lines.all()),
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
    req = (
        PriceRequest.objects.filter(supplier=company, pk=request_id)
        .select_related("answer_currency")
        .prefetch_related(Prefetch("lines", queryset=PriceRequestLine.objects.order_by("id")))
        .first()
    )
    if req is None:
        return None

    lines = [
        {
            "id": line.id,
            "name": line.name,
            "article": line.article or "",
            "quantity": line.quantity,
            "unit": line.unit or "",
            "answer_price": _format_money(line.answer_price) if line.answer_price is not None else None,
        }
        for line in req.lines.all()
    ]

    return {
        "id": req.id,
        "requested_at": req.requested_at,
        "subject": req.subject,
        "note": req.note or "",
        "status": "answered" if req.answered_at else req.status,
        "answered_at": req.answered_at,
        "answer_note": req.answer_note or "",
        "answer_currency": req.answer_currency.code if req.answer_currency else None,
        "lines": lines,
    }


def _resolve_currency(code: Optional[str], prices: list[dict]):
    """Валюта цен ответа: без цен не нужна, с ценами обязательна и должна быть в справочнике."""
    from master_data.models import Currency

    if not prices:
        return None
    currency = Currency.objects.filter(code=code).first() if code else None
    if currency is None:
        raise PortalValidationError("VALIDATION_ERROR")
    return currency


def _update_supplier_price(company, user, product_id: int, price: Decimal, currency, valid_until) -> None:
    """Цена партнёра на товар строки (spec K2) — как при загрузке его прайса: истёкшая цена не подтверждается."""
    from catalog.models import SupplierOffer

    today = timezone.localdate()
    defaults: dict[str, Any] = {
        "base_price": price,
        "currency": currency,
        "is_active": True,
        "source": SupplierOffer.Source.RFQ_REPLY,
    }
    until = valid_until
    if until is not None:
        defaults["valid_until"] = until
    else:
        until = (
            SupplierOffer.objects.filter(product_id=product_id, supplier=company)
            .values_list("valid_until", flat=True)
            .first()
        )
    if until is None or until >= today:
        defaults["confirmed_at"] = timezone.now()
        defaults["confirmed_by_contact"] = user
    with pghistory.context(contact=user.pk, source="rfq_reply"):
        SupplierOffer.objects.update_or_create(product_id=product_id, supplier=company, defaults=defaults)


def _apply_prices(company, user, req: PriceRequest, prices: list[dict], currency, valid_until) -> int:
    """Записать цены ответа: строка должна быть строкой этого запроса; вернуть число позиций с ценой."""
    if not prices:
        return 0
    ids = [row["id"] for row in prices]
    if len(ids) != len(set(ids)):
        raise PortalValidationError("VALIDATION_ERROR")
    lines = {line.pk: line for line in req.lines.select_related("quote_item").filter(pk__in=ids)}
    if len(lines) != len(ids):
        raise PortalValidationError("VALIDATION_ERROR")
    for row in prices:
        line = lines[row["id"]]
        line.answer_price = row["unit_price"]
        line.save(update_fields=["answer_price"])
        product_id = line.quote_item.product_id if line.quote_item_id else None
        if product_id:
            _update_supplier_price(company, user, product_id, row["unit_price"], currency, valid_until)
    return len(prices)


def respond_partner_price_request(
    company,
    user,
    request_id: int,
    answer_note: str,
    prices: Optional[list[dict]] = None,
    currency_code: Optional[str] = None,
    valid_until: Optional[date] = None,
) -> Optional[dict]:
    """Ответ партнёра на запрос цен: один раз и только на доставленный запрос."""
    prices = prices or []
    with transaction.atomic():
        req = (
            PriceRequest.objects.select_for_update(of=("self",))
            .select_related("requested_by", "deal")
            .filter(supplier=company, pk=request_id)
            .first()
        )
        if req is None:
            return None
        if req.status != PriceRequestStatus.SENT:
            raise PortalConflict("REQUEST_NOT_SENT")
        if req.answered_at is not None:
            raise PortalConflict("ALREADY_ANSWERED")
        if valid_until is not None and valid_until < timezone.localdate():
            raise PortalValidationError("VALIDATION_ERROR")
        currency = _resolve_currency(currency_code, prices)

        priced = _apply_prices(company, user, req, prices, currency, valid_until)
        req.answered_at = timezone.now()
        req.answered_by = _custom_user_or_none(user)
        req.answer_note = answer_note.strip()[:1000]
        req.answer_currency = currency
        req.save(update_fields=["answered_at", "answered_by", "answer_note", "answer_currency"])

    _notify_supply(
        company,
        req.requested_by,
        title=f"Партнёр ответил на запрос цен: {req.subject}"[:255],
        message=f"«{company.name}»: {req.answer_note}"
        + (f" Цены по позициям: {priced}, цена поставщика обновлена." if priced else ""),
        event_code=EVENT_RFQ_ANSWERED,
        params={"supplier": company.name, "request_id": req.pk, "priced": priced},
        deal=req.deal,
    )
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
