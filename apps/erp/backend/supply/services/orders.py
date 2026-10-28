"""Заказы поставщикам и приёмка (D2-2, SPEC-v3 §7.4 «Склад», integration-map ERP-14).

* Номер ЗП-ГГГГ-NNN — счётчик года под блокировкой (`inventory.services.stock.next_number`), без пропусков.
* Статусы: черновик → отправлен → подтверждён → получен (+ «отменён»). Переход — только допустимый (`TRANSITIONS`), под
  `select_for_update` строки заказа; недопустимый — 409 `TRANSITION_NOT_ALLOWED`. Правка состава — только в черновике.
* «Отправить» — письмо поставщику (почта ERP, шаблон `supplier_order`) и запись в журнале заказа; без адреса поставщика —
  409 `SUPPLIER_EMAIL_REQUIRED`, сбой почты — 409 `EMAIL_FAILED` (статус не меняется). «Подтвердить» — нужна ожидаемая дата.
* Приёмка частичная: каждая приёмка увеличивает остаток склада (журнал движений) и `received_quantity` строки; строка с
  привязкой к проекту (`deal`, `quote_item`) после приёмки резервируется под этот проект (в пределах количества строки
  КП). Все строки получены целиком — заказ «получен».
* Цена в строке и сумма заказа — цены поставщика: видит `quote.view_cost_margin` или зона товаров (`quote.visa_goods`),
  задаёт — они же (403 `PRICES_FORBIDDEN`); остальные получают `null`.
* Просроченный заказ: ожидаемая дата прошла, заказ отправлен или подтверждён, но не получен (`overdue_orders`).

Ошибки — `StockError(code, status)`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from inventory.access import (
    StockError,
    can_manage_fulfillment,
    can_manage_supply,
    can_see_supplier_prices,
    person_name,
    require_staff,
    require_supply,
)
from inventory.models import MovementKind, Reservation, ReservationStatus
from inventory.services import stock
from supply.models import (
    TRANSITIONS,
    GoodsReceipt,
    GoodsReceiptLine,
    OrderLogKind,
    OrderStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderLog,
)

from catalog.models import Product

logger = logging.getLogger(__name__)

MAX_LINES = 200
MAX_ROWS = 300
_CENT = Decimal("0.01")
OVERDUE_STATUSES = (OrderStatus.SENT, OrderStatus.CONFIRMED)


# ── помощники ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _money(value: Any) -> Optional[str]:
    if value is None:
        return None
    return f"{Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP):.2f}"


def _log(order: SupplierOrder, kind: str, user, detail: str = "") -> None:
    SupplierOrderLog.objects.create(
        order=order, kind=kind, user=user if getattr(user, "pk", None) else None, detail=detail[:500]
    )


def _own_company_id() -> Optional[int]:
    from core.tenant import own_company_id

    return own_company_id()


def today() -> date:
    return timezone.localdate()


def is_overdue(order: SupplierOrder, *, on: Optional[date] = None) -> bool:
    return bool(order.expected_date) and order.status in OVERDUE_STATUSES and order.expected_date < (on or today())


def supplier_email(company) -> str:
    """Адрес поставщика: почта компании, иначе почта основного (или первого) контакта."""
    if company.email:
        return company.email
    contact = company.contacts.exclude(email="").order_by("-is_primary", "id").first()
    return contact.email if contact is not None else ""


def get_supplier(supplier_id: int):
    """Внешний поставщик (тип SUPPLIER, не своя компания, не в архиве) или 404/409."""
    from parties.models import Company

    company = Company.objects.sellers().exclude(pk=_own_company_id() or 0).filter(pk=supplier_id).first()
    if company is None:
        raise StockError("SUPPLIER_NOT_FOUND", 404)
    return company


def _order_or_404(order_id: int, *, lock: bool = False) -> SupplierOrder:
    qs = SupplierOrder.objects.select_related("supplier", "currency", "created_by")
    if lock:
        qs = qs.select_for_update(of=("self",))
    order = qs.filter(pk=order_id).first()
    if order is None:
        raise StockError("ORDER_NOT_FOUND", 404)
    return order


# ── ввод ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class LineInput:
    quantity: int
    id: Optional[int] = None
    product_id: Optional[int] = None
    name: str = ""
    article: str = ""
    unit: str = ""
    unit_price: Optional[Decimal] = None
    price_given: bool = False  # ключ цены был в теле (None — «очистить»)
    deal_id: Optional[int] = None
    quote_item_id: Optional[int] = None
    link_given: bool = False  # ключи проекта были в теле (None — «отвязать»)


@dataclass
class OrderInput:
    supplier_id: Optional[int] = None
    expected_date: Optional[date] = None
    expected_given: bool = False
    note: Optional[str] = None
    currency: Optional[str] = None
    lines: Optional[list[LineInput]] = field(default=None)


def _currency(code: Optional[str]):
    from master_data.models import Currency

    if not code:
        return None
    currency = Currency.objects.filter(code=code.upper()).first()
    if currency is None:
        raise StockError("BAD_CURRENCY", 400)
    return currency


def _check_price_rights(user, lines: list[LineInput]) -> None:
    if any(line.price_given and line.unit_price is not None for line in lines) and not can_see_supplier_prices(user):
        raise StockError("PRICES_FORBIDDEN", 403)


def _resolve_lines(lines: list[LineInput]) -> list[dict]:
    """Строки заказа: карточка каталога обязательна (на склад заводится только каталожный товар), проект и строка
    расчёта — согласованы между собой."""
    if len(lines) > MAX_LINES:
        raise StockError("TOO_MANY_LINES", 400)
    products = {
        p.pk: p
        for p in Product.objects.select_related("uom", "domain_type").filter(
            pk__in=[row.product_id for row in lines if row.product_id]
        )
    }
    from sales.models import QuoteItem

    items = {
        i.pk: i
        for i in QuoteItem.objects.select_related("quote").filter(
            pk__in=[row.quote_item_id for row in lines if row.quote_item_id]
        )
    }
    rows = []
    for line in lines:
        if not line.product_id:
            raise StockError("PRODUCT_REQUIRED", 400)
        product = products.get(line.product_id)
        if product is None:
            raise StockError("PRODUCT_NOT_FOUND", 400)
        if product.is_service:
            raise StockError("SERVICE_NOT_STOCKED", 400)
        if line.quantity < 1:
            raise StockError("QUANTITY_OUT_OF_RANGE", 400)
        deal_id, item_id = line.deal_id, line.quote_item_id
        if item_id:
            item = items.get(item_id)
            if item is None:
                raise StockError("LINE_NOT_FOUND", 400)
            if deal_id and item.quote.deal_id != deal_id:
                raise StockError("LINE_NOT_IN_DEAL", 400)
            if item.product_id != product.pk:
                # строка расчёта другого товара: резерв ушёл бы не туда
                raise StockError("LINE_PRODUCT_MISMATCH", 400)
            deal_id = item.quote.deal_id
        rows.append(
            {
                "id": line.id,
                "product": product,
                "name": (line.name or product.name)[:500],
                "article": (line.article or product.manufacturer_part_number or product.sku or "")[:120],
                "unit": (line.unit or (product.uom.name if product.uom_id else ""))[:32],
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "price_given": line.price_given,
                "link_given": line.link_given,
                "deal_id": deal_id,
                "quote_item_id": item_id,
            }
        )
    return rows


def _write_lines(order: SupplierOrder, rows: list[dict], user) -> None:
    """Заменить состав черновика: строки с `id` обновляются (цена не трогается, если её нет в теле), без `id` —
    создаются, отсутствующие в теле — удаляются."""
    existing = {line.pk: line for line in order.lines.all()}
    keep: set[int] = set()
    for position, row in enumerate(rows, start=1):
        line = existing.get(row["id"]) if row["id"] else None
        if row["id"] and line is None:
            raise StockError("LINE_NOT_FOUND", 404)  # объектная проверка: строка чужого заказа не правится
        values = dict(
            position=position,
            product=row["product"],
            name=row["name"],
            article=row["article"],
            unit=row["unit"],
            quantity=row["quantity"],
        )
        if line is None or row["link_given"]:
            values.update(
                deal_id=row["deal_id"], quote_item_id=row["quote_item_id"]
            )  # привязка к проекту не слетает при правке
        if line is None:
            SupplierOrderLine.objects.create(order=order, unit_price=row["unit_price"], **values)
            continue
        keep.add(line.pk)
        for key, value in values.items():
            setattr(line, key, value)
        if row["price_given"]:
            line.unit_price = row["unit_price"]
        line.save()
    stale = [pk for pk in existing if pk not in keep]
    if stale:
        order.lines.filter(pk__in=stale).delete()


# ── создание и правка ──────────────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_order(user, data: OrderInput) -> SupplierOrder:
    require_supply(user)
    if data.supplier_id is None:
        raise StockError("SUPPLIER_REQUIRED", 400)
    supplier = get_supplier(data.supplier_id)
    lines = data.lines or []
    if not lines:
        raise StockError("LINES_REQUIRED", 400)
    _check_price_rights(user, lines)
    rows = _resolve_lines(lines)
    number, year, seq = stock.next_number("PO", "ЗП")
    order = SupplierOrder.objects.create(
        number=number,
        number_year=year,
        number_seq=seq,
        supplier=supplier,
        expected_date=data.expected_date,
        currency=_currency(data.currency),
        note=(data.note or "")[:5000],
        created_by=user if getattr(user, "pk", None) else None,
    )
    _write_lines(order, rows, user)
    _log(order, OrderLogKind.CREATED, user, supplier.name)
    return order


@transaction.atomic
def create_from_deal(user, deal_id: int, supplier_id: int) -> SupplierOrder:
    """Черновик ЗП на дефицит проекта: по каждой строке-товару последнего КП заявки — недостающее количество (количество
    строки − удерживаемое резервом − уже заказанное в живых ЗП). Нечего заказывать — 409 `NO_SHORTAGE`."""
    from sales.models import Deal

    from crm.services.calculation import calc_quote, zone_of

    require_supply(user)
    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        raise StockError("DEAL_NOT_FOUND", 404)
    supplier = get_supplier(supplier_id)
    quote = calc_quote(deal) or deal.quotes.order_by("-version").first()
    if quote is None:
        raise StockError("NO_SHORTAGE", 409)
    items = [
        item
        for item in quote.items.billable().select_related("product__domain_type", "product__uom", "calc")
        if item.product_id and zone_of(item) == "goods"
    ]
    reserved = stock.reserved_by_item(i.pk for i in items)
    ordered = {
        row["quote_item_id"]: row["total"] or 0
        for row in SupplierOrderLine.objects.filter(
            quote_item__in=items, order__status__in=(OrderStatus.DRAFT, *OVERDUE_STATUSES)
        )
        .values("quote_item_id")
        .annotate(total=Sum("quantity") - Sum("received_quantity"))
    }
    lines = []
    for item in items:
        shortage = item.quantity - reserved.get(item.pk, 0) - ordered.get(item.pk, 0)
        if shortage > 0:
            lines.append(
                LineInput(quantity=shortage, product_id=item.product_id, deal_id=deal.pk, quote_item_id=item.pk)
            )
    if not lines:
        raise StockError("NO_SHORTAGE", 409)
    return create_order(
        user, OrderInput(supplier_id=supplier.pk, lines=lines, note=f"Дефицит проекта {deal.number}".strip())
    )


@transaction.atomic
def update_order(user, order_id: int, data: OrderInput) -> SupplierOrder:
    require_supply(user)
    order = _order_or_404(order_id, lock=True)
    editable_fields = data.lines is not None or data.supplier_id is not None
    if order.status != OrderStatus.DRAFT and editable_fields:
        raise StockError("ORDER_NOT_DRAFT", 409)
    if order.status in (OrderStatus.RECEIVED, OrderStatus.CANCELLED):
        raise StockError("ORDER_CLOSED", 409)
    changed = []
    if data.supplier_id is not None and data.supplier_id != order.supplier_id:
        order.supplier = get_supplier(data.supplier_id)
        changed.append("поставщик")
    if data.expected_given and data.expected_date != order.expected_date:
        order.expected_date = data.expected_date
        order.overdue_notified_at = None  # новая дата — о просрочке можно сообщить заново
        changed.append("ожидаемая дата")
    if data.note is not None and data.note != order.note:
        order.note = data.note[:5000]
        changed.append("примечание")
    if data.currency is not None:
        order.currency = _currency(data.currency)
        changed.append("валюта")
    if data.lines is not None:
        if not data.lines:
            raise StockError("LINES_REQUIRED", 400)
        _check_price_rights(user, data.lines)
        _write_lines(order, _resolve_lines(data.lines), user)
        changed.append("состав")
    if changed:
        order.save()
        _log(order, OrderLogKind.EDITED, user, ", ".join(changed))
    return order


# ── статусы ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _transition(order: SupplierOrder, target: str) -> None:
    if target not in TRANSITIONS.get(order.status, ()):
        raise StockError("TRANSITION_NOT_ALLOWED", 409, current=order.status, target=target)


@transaction.atomic
def send_order(user, order_id: int, *, to_email: str = "") -> SupplierOrder:
    from notifications.emails import EmailDeliveryError, send_templated_email

    require_supply(user)
    order = _order_or_404(order_id, lock=True)
    _transition(order, OrderStatus.SENT)
    lines = list(order.lines.select_related("product"))
    if not lines:
        raise StockError("LINES_REQUIRED", 409)
    recipient = (to_email or "").strip() or supplier_email(order.supplier)
    if not recipient:
        raise StockError("SUPPLIER_EMAIL_REQUIRED", 409)
    context = {
        "supplier_name": order.supplier.name,
        "number": order.number,
        "expected_date": order.expected_date.strftime("%d.%m.%Y") if order.expected_date else "",
        "note": order.note,
        "sender_name": person_name(user),
        "lines": [
            {
                "name": line.name,
                "article": line.article,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": _money(line.unit_price) if line.unit_price is not None else "",
            }
            for line in lines
        ],
        "with_prices": any(line.unit_price is not None for line in lines),
    }
    try:
        send_templated_email(
            "supplier_order",
            context,
            to=[recipient],
            channel="transactional",
            user=None,
            language=order.supplier.language or None,
            reply_to=[user.email] if getattr(user, "email", "") else None,
        )
    except EmailDeliveryError as exc:
        logger.warning("Заказ %s не отправлен: %s", order.number, exc)
        raise StockError("EMAIL_FAILED", 409) from exc
    order.status = OrderStatus.SENT
    order.sent_at = timezone.now()
    order.sent_by = user if getattr(user, "pk", None) else None
    order.sent_to = recipient
    order.save(update_fields=["status", "sent_at", "sent_by", "sent_to", "updated_at"])
    _log(order, OrderLogKind.SENT, user, recipient)
    return order


@transaction.atomic
def confirm_order(user, order_id: int, *, expected_date: Optional[date] = None) -> SupplierOrder:
    require_supply(user)
    order = _order_or_404(order_id, lock=True)
    _transition(order, OrderStatus.CONFIRMED)
    if expected_date is not None:
        order.expected_date = expected_date
    if order.expected_date is None:
        raise StockError("EXPECTED_DATE_REQUIRED", 409)
    order.status = OrderStatus.CONFIRMED
    order.confirmed_at = timezone.now()
    order.confirmed_by = user if getattr(user, "pk", None) else None
    order.overdue_notified_at = None
    order.save(
        update_fields=["status", "confirmed_at", "confirmed_by", "expected_date", "overdue_notified_at", "updated_at"]
    )
    _log(order, OrderLogKind.CONFIRMED, user, order.expected_date.isoformat())
    return order


@transaction.atomic
def cancel_order(user, order_id: int, *, reason: str = "") -> SupplierOrder:
    require_supply(user)
    order = _order_or_404(order_id, lock=True)
    _transition(order, OrderStatus.CANCELLED)
    if order.receipts.exists():
        raise StockError("ORDER_HAS_RECEIPTS", 409)  # часть уже принята: остаток закрывается приёмкой, а не отменой
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = user if getattr(user, "pk", None) else None
    order.cancel_reason = reason.strip()[:500]
    order.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason", "updated_at"])
    _log(order, OrderLogKind.CANCELLED, user, order.cancel_reason)
    return order


# ── приёмка ────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class ReceiptInput:
    order_line_id: int
    quantity: int
    cell: str = ""


def _reserve_for_project(line: SupplierOrderLine, quantity: int, user) -> None:
    """Принятое по строке с проектом закрепляется за ним: резерв строки КП растёт на принятое, но не выше количества
    строки КП (лишнее остаётся свободным на складе). Проигранная или закрытая заявка резерв не получает."""
    item = line.quote_item
    if item is None or line.deal_id is None or item.product_id != line.product_id:
        return
    stage = line.deal.stage.code if line.deal.stage_id else ""
    if stage in stock.CLOSED_STAGES:
        return
    current = Reservation.objects.select_for_update().filter(quote_item=item, status=ReservationStatus.ACTIVE).first()
    held = current.quantity if current else 0
    add = min(quantity, max(item.quantity - held, 0))
    if add <= 0:
        return
    if current is None:
        Reservation.objects.create(
            product_id=line.product_id,
            deal_id=line.deal_id,
            quote_item=item,
            quantity=add,
            created_by=user if getattr(user, "pk", None) else None,
        )
    else:
        current.quantity += add
        current.save(update_fields=["quantity"])


@transaction.atomic
def receive(user, order_id: int, lines: list[ReceiptInput], *, supplier_doc: str = "", note: str = "") -> SupplierOrder:
    require_supply(user)
    if not lines:
        raise StockError("LINES_REQUIRED", 400)
    if len({line.order_line_id for line in lines}) != len(lines):
        raise StockError("DUPLICATE_LINE", 400)
    order = _order_or_404(order_id, lock=True)
    if order.status != OrderStatus.CONFIRMED:
        raise StockError("ORDER_NOT_CONFIRMED", 409, current=order.status)
    order_lines = {
        line.pk: line
        for line in order.lines.select_for_update(of=("self",)).select_related("product", "deal__stage", "quote_item")
    }
    for item in lines:
        # Объектная проверка: строка приёмки должна принадлежать этому заказу.
        if item.order_line_id not in order_lines:
            raise StockError("LINE_NOT_FOUND", 404)
        if order_lines[item.order_line_id].product_id is None:
            raise StockError("PRODUCT_REQUIRED", 409)  # карточку товара удалили — оприходовать некуда
    stock.lock_products(order_lines[i.order_line_id].product_id for i in lines)
    warehouse = stock.default_warehouse()
    receipt = GoodsReceipt.objects.create(
        order=order,
        supplier_doc=supplier_doc.strip()[:100],
        note=note.strip()[:500],
        received_by=user if getattr(user, "pk", None) else None,
    )
    total = 0
    for item in lines:
        line = order_lines[item.order_line_id]
        if item.quantity < 1 or item.quantity > line.left:
            raise StockError("QUANTITY_OUT_OF_RANGE", 400, max=line.left)
        cell = (item.cell or "").strip()
        stock.add_stock(
            line.product_id,
            item.quantity,
            kind=MovementKind.RECEIPT,
            user=user,
            cell=cell,
            warehouse=warehouse,
            source_id=receipt.pk,
            note=order.number,
        )
        line.received_quantity += item.quantity
        line.save(update_fields=["received_quantity"])
        GoodsReceiptLine.objects.create(
            receipt=receipt, order_line=line, quantity=item.quantity, warehouse=warehouse, cell=cell[:32]
        )
        _reserve_for_project(line, item.quantity, user)
        total += item.quantity
    _log(
        order,
        OrderLogKind.RECEIPT,
        user,
        f"{total} шт." + (f" · накладная {receipt.supplier_doc}" if receipt.supplier_doc else ""),
    )
    if all(line.received_quantity >= line.quantity for line in order_lines.values()):
        order.status = OrderStatus.RECEIVED
        order.received_at = timezone.now()
        order.save(update_fields=["status", "received_at", "updated_at"])
        _log(order, OrderLogKind.RECEIVED, user)
    return order


# ── чтение ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _receipt_state(order: SupplierOrder, lines) -> str:
    received = sum(line.received_quantity for line in lines)
    wanted = sum(line.quantity for line in lines)
    if received == 0:
        return "none"
    return "full" if received >= wanted else "partial"


def _deal_ref(deal) -> Optional[dict]:
    if deal is None:
        return None
    return {"id": deal.pk, "number": deal.number or None, "client_name": deal.company.name if deal.company_id else None}


def present_order(order: SupplierOrder, user, *, detail: bool = False) -> dict:
    prices = can_see_supplier_prices(user)
    manage = can_manage_supply(user)
    lines = list(order.lines.all())
    overdue = is_overdue(order)
    total = sum((line.unit_price * line.quantity for line in lines if line.unit_price is not None), Decimal("0"))
    deals: dict[int, Any] = {}
    for line in lines:
        if line.deal_id and line.deal_id not in deals:
            deals[line.deal_id] = line.deal
    status = order.status
    row = {
        "id": order.pk,
        "number": order.number,
        "status": status,
        "supplier": {"id": order.supplier_id, "name": order.supplier.name},
        "expected_date": order.expected_date.isoformat() if order.expected_date else None,
        "overdue": overdue,
        "days_overdue": (today() - order.expected_date).days if overdue else None,
        "currency": order.currency.code if order.currency_id else None,
        "lines_count": len(lines),
        "quantity": sum(line.quantity for line in lines),
        "received_quantity": sum(line.received_quantity for line in lines),
        "receipt_state": _receipt_state(order, lines),
        "total": _money(total) if prices and any(line.unit_price is not None for line in lines) else None,
        "projects": [_deal_ref(deal) for deal in deals.values()],
        "created_at": order.created_at.isoformat(),
        "created_by_name": person_name(order.created_by) if order.created_by_id else None,
        "actions": {
            "edit": manage and status == OrderStatus.DRAFT,
            "send": manage and status == OrderStatus.DRAFT,
            "confirm": manage and status == OrderStatus.SENT,
            "receive": manage and status == OrderStatus.CONFIRMED,
            "cancel": manage
            and status in (OrderStatus.DRAFT, OrderStatus.SENT, OrderStatus.CONFIRMED)
            and not any(line.received_quantity for line in lines),
        },
    }
    if not detail:
        return row
    row.update(
        {
            "supplier": {
                "id": order.supplier_id,
                "name": order.supplier.name,
                "email": supplier_email(order.supplier) or None,
            },
            "note": order.note,
            "sent_at": order.sent_at.isoformat() if order.sent_at else None,
            "sent_to": order.sent_to or None,
            "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
            "received_at": order.received_at.isoformat() if order.received_at else None,
            "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
            "cancel_reason": order.cancel_reason or None,
            "lines": [
                {
                    "id": line.pk,
                    "position": line.position,
                    "product_id": line.product_id,
                    "name": line.name,
                    "article": line.article,
                    "unit": line.unit,
                    "quantity": line.quantity,
                    "received_quantity": line.received_quantity,
                    "unit_price": _money(line.unit_price) if prices and line.unit_price is not None else None,
                    "line_total": (
                        _money(line.unit_price * line.quantity) if prices and line.unit_price is not None else None
                    ),
                    "deal": _deal_ref(line.deal),
                    "quote_item_id": line.quote_item_id,
                }
                for line in lines
            ],
            "receipts": [
                {
                    "id": receipt.pk,
                    "received_at": receipt.received_at.isoformat(),
                    "received_by_name": person_name(receipt.received_by) if receipt.received_by_id else None,
                    "supplier_doc": receipt.supplier_doc or None,
                    "note": receipt.note or None,
                    "lines": [
                        {
                            "order_line_id": rl.order_line_id,
                            "name": rl.order_line.name,
                            "quantity": rl.quantity,
                            "cell": rl.cell or None,
                        }
                        for rl in receipt.lines.all()
                    ],
                }
                for receipt in order.receipts.select_related("received_by").prefetch_related("lines__order_line")
            ],
            "log": [
                {
                    "kind": entry.kind,
                    "at": entry.created_at.isoformat(),
                    "by_name": person_name(entry.user) if entry.user_id else None,
                    "detail": entry.detail or None,
                }
                for entry in order.log.select_related("user")
            ],
        }
    )
    return row


def _list_queryset():
    return SupplierOrder.objects.select_related("supplier", "currency", "created_by").prefetch_related(
        "lines__deal__company"
    )


def list_orders(
    user,
    *,
    status: str = "",
    supplier_id: Optional[int] = None,
    q: str = "",
    number: str = "",
    overdue: bool = False,
) -> dict:
    require_staff(user)
    qs = _list_queryset()
    if number:
        qs = qs.filter(number=number)
    if status:
        qs = qs.filter(status=status)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if overdue:
        qs = qs.filter(status__in=OVERDUE_STATUSES, expected_date__lt=today())
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(supplier__name__icontains=q) | Q(lines__name__icontains=q)).distinct()
    rows = list(qs.order_by("-created_at", "-id")[:MAX_ROWS])
    return {
        "results": [present_order(order, user) for order in rows],
        "rights": order_rights(user),
    }


def order_rights(user) -> dict:
    return {
        "manage": can_manage_supply(user),
        "ship": can_manage_fulfillment(user),
        "prices": can_see_supplier_prices(user),
    }


def get_order(user, order_id: int) -> dict:
    require_staff(user)
    order = _list_queryset().filter(pk=order_id).first()
    if order is None:
        raise StockError("ORDER_NOT_FOUND", 404)
    return {**present_order(order, user, detail=True), "rights": order_rights(user)}


def present_detail(user, order: SupplierOrder) -> dict:
    """Карточка заказа после действия (перечитана с предзагрузкой строк)."""
    order = _list_queryset().get(pk=order.pk)
    return {**present_order(order, user, detail=True), "rights": order_rights(user)}


# ── просрочка ──────────────────────────────────────────────────────────────────────────────────────────────────────


def overdue_orders(user) -> list[dict]:
    """Источник вида очереди `supplier_overdue`: просроченные заказы (ожидаемая дата прошла, не получены). Видит держатель
    права снабжения: очередь — рабочий список действий, а не справка."""
    require_supply(user)
    qs = _list_queryset().filter(status__in=OVERDUE_STATUSES, expected_date__lt=today()).order_by("expected_date", "id")
    return [
        {
            "id": order.pk,
            "number": order.number,
            "status": order.status,
            "supplier_name": order.supplier.name,
            "expected_date": order.expected_date.isoformat(),
            "days_overdue": (today() - order.expected_date).days,
        }
        for order in qs[:MAX_ROWS]
    ]


def notify_overdue() -> int:
    """Уведомить о просроченных заказах (раз на заказ): создатель заказа и держатели права снабжения. Вызывает задача
    Celery раз в сутки; повторный вызов того же дня ничего не шлёт."""
    from accounts.models import CustomUser
    from accounts.services.permissions import staff_has_permission
    from notifications.services import notify_user

    sent = 0
    qs = _list_queryset().filter(
        status__in=OVERDUE_STATUSES, expected_date__lt=today(), overdue_notified_at__isnull=True
    )
    company_id = _own_company_id()
    holders = []
    if company_id:
        holders = [
            u
            for u in CustomUser.objects.filter(
                is_active=True, memberships__is_active=True, memberships__company_id=company_id
            ).distinct()
            if staff_has_permission(u, "supply.manage")
        ]
    for order in qs:
        with transaction.atomic():
            fresh = SupplierOrder.objects.select_for_update().get(pk=order.pk)
            if fresh.overdue_notified_at is not None:
                continue
            recipients = {u.pk: u for u in holders}
            if order.created_by_id and order.created_by.is_active:
                recipients[order.created_by_id] = order.created_by
            days = (today() - order.expected_date).days
            for recipient in recipients.values():
                notify_user(
                    user=recipient,
                    title=f"Заказ {order.number} просрочен",
                    message=f"Поставщик {order.supplier.name} не поставил товар к {order.expected_date.strftime('%d.%m.%Y')} (просрочка {days} дн.)",
                    link=f"/erp/stock/{order.number}",
                    type_code="WARNING",
                    event_code="supplier_order.overdue",
                    event_params={
                        "number": order.number,
                        "supplier": order.supplier.name,
                        "expected_date": order.expected_date.isoformat(),
                        "days": days,
                    },
                )
                sent += 1
            fresh.overdue_notified_at = timezone.now()
            fresh.save(update_fields=["overdue_notified_at"])
            _log(fresh, OrderLogKind.OVERDUE, None, f"{days} дн.")
    return sent
