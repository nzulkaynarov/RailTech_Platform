"""Прослеживаемость-минимум (ADR-0021, L0-3): серийные номера и партии как разрез склада.

Класс учёта — данные категории товара (`catalog.Category.tracking`, `requires_conformity_doc`): S — каждая единица по
серийному номеру, L — партия изготовителя со сроком годности, N — только количество (по умолчанию, ничего нового). Номер
вводится на приёмке (`supply.services.orders.receive`) и обязателен на отгрузке (`inventory.services.stock.ship`). Остаток по
количеству не меняется: единица (`TraceUnit`) хранит ссылку на строку приёмки, распределение (`TraceAllocation`) — на строку
отгрузки. Поиск по номеру отвечает «откуда» и «куда».

Эталоны: Odoo «Track Inventory» (By Lots / By Unique Serial Number, номер обязателен при «Validate»), Business Central «Item
Tracking Code» (Specific Tracking), 1С:ERP «политика учёта серий», SAP batch management и serial number profile.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import Prefetch, Q
from django.utils import timezone

from catalog.constants import TrackingClass

from ..access import StockError, require_staff
from ..models import TraceAllocation, TraceKind, TraceStatus, TraceUnit

MAX_SERIALS = 1000
NUMBER_MAX = 100
SEARCH_MIN = 2
SEARCH_LIMIT = 50


@dataclass
class ReceiptTracking:
    """Что ввели на строке приёмки: серийные (S), партия и срок годности (L), документ соответствия (если нужен)."""

    serials: list[str] = field(default_factory=list)
    lot: str = ""
    expiry: Optional[datetime.date] = None
    doc_number: str = ""
    doc_valid_until: Optional[datetime.date] = None


@dataclass
class UnitPick:
    """Выбор на строке отгрузки: единица и сколько из неё (серийный — 1)."""

    unit_id: int
    quantity: int = 1


def tracking_of(product) -> str:
    """Класс учёта товара — класс его категории; без категории — только количество."""
    category = getattr(product, "category", None)
    return getattr(category, "tracking", None) or TrackingClass.NONE


def requires_doc(product) -> bool:
    category = getattr(product, "category", None)
    return bool(getattr(category, "requires_conformity_doc", False))


def _clean(number: str) -> str:
    return (number or "").strip()


# ── приёмка ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _check_serials(product, quantity: int, serials: list[str]) -> list[str]:
    numbers = [_clean(n) for n in serials if _clean(n)]
    if not numbers:
        raise StockError("SERIALS_REQUIRED", 400, expected=quantity)
    if len(numbers) > MAX_SERIALS or any(len(n) > NUMBER_MAX for n in numbers):
        raise StockError("SERIAL_INVALID", 400)
    if len(numbers) != quantity:
        raise StockError("SERIALS_COUNT_MISMATCH", 400, expected=quantity, given=len(numbers))
    seen: set[str] = set()
    for number in numbers:
        if number in seen:
            raise StockError("SERIAL_DUPLICATE", 400, number=number)
        seen.add(number)
    taken = TraceUnit.objects.filter(product=product, kind=TraceKind.SERIAL, number__in=numbers).first()
    if taken is not None:
        raise StockError("SERIAL_EXISTS", 409, number=taken.number)
    return numbers


def _check_doc(product, data: ReceiptTracking) -> tuple[str, Optional[datetime.date]]:
    if not requires_doc(product):
        return "", None
    number = _clean(data.doc_number)
    if not number or len(number) > NUMBER_MAX:
        raise StockError("CONFORMITY_DOC_REQUIRED", 400)
    if data.doc_valid_until is None:
        raise StockError("CONFORMITY_DOC_VALID_UNTIL_REQUIRED", 400)
    if data.doc_valid_until < timezone.localdate():
        raise StockError("CONFORMITY_DOC_EXPIRED", 400)
    return number, data.doc_valid_until


def validate_receipt(product, quantity: int, data: Optional[ReceiptTracking]) -> ReceiptTracking:
    """Проверить ввод строки приёмки по классу категории; для N ввод номеров игнорируется. Возвращает очищенный ввод."""
    data = data or ReceiptTracking()
    doc_number, doc_valid_until = _check_doc(product, data)
    kind = tracking_of(product)
    clean = ReceiptTracking(doc_number=doc_number, doc_valid_until=doc_valid_until)
    if kind == TrackingClass.SERIAL:
        clean.serials = _check_serials(product, quantity, data.serials)
    elif kind == TrackingClass.LOT:
        lot = _clean(data.lot)
        if not lot:
            raise StockError("LOT_REQUIRED", 400)
        if len(lot) > NUMBER_MAX:
            raise StockError("LOT_INVALID", 400)
        clean.lot, clean.expiry = lot, data.expiry
    return clean


def record_receipt(receipt_line, product, data: ReceiptTracking) -> list[TraceUnit]:
    """Единицы прослеживаемости принятой строки (S — по одной на серийный, L — одна партия на строку)."""
    if data.serials:
        return TraceUnit.objects.bulk_create(
            [
                TraceUnit(kind=TraceKind.SERIAL, product=product, number=n, quantity=1, receipt_line=receipt_line)
                for n in data.serials
            ]
        )
    if data.lot:
        unit = TraceUnit.objects.create(
            kind=TraceKind.LOT,
            product=product,
            number=data.lot,
            expiry_date=data.expiry,
            quantity=receipt_line.quantity,
            receipt_line=receipt_line,
        )
        return [unit]
    return []


# ── отгрузка ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def free_units(product_ids: Iterable[int]) -> dict[int, list[TraceUnit]]:
    """Свободные единицы по товарам (что ещё на складе): серийные по номеру, партии — раньше истекающие первыми."""
    units = TraceUnit.objects.filter(product_id__in=list(product_ids), status=TraceStatus.IN_STOCK).order_by(
        "product_id", "expiry_date", "number", "id"
    )
    out: dict[int, list[TraceUnit]] = {}
    for unit in units:
        out.setdefault(unit.product_id, []).append(unit)
    return out


def validate_picks(product, quantity: int, picks: list[UnitPick]) -> list[tuple[TraceUnit, int]]:
    """Проверить выбор единиц строки отгрузки под блокировкой: S/L — сумма = количеству, только свободные этого товара."""
    kind = tracking_of(product)
    if kind == TrackingClass.NONE:
        return []
    if not picks:
        raise StockError("UNITS_REQUIRED", 400, expected=quantity)
    ids = [p.unit_id for p in picks]
    if len(set(ids)) != len(ids):
        raise StockError("UNIT_DUPLICATE", 400)
    units = {u.pk: u for u in TraceUnit.objects.select_for_update().filter(pk__in=ids)}
    wanted_kind = TraceKind.SERIAL if kind == TrackingClass.SERIAL else TraceKind.LOT
    chosen: list[tuple[TraceUnit, int]] = []
    for pick in picks:
        unit = units.get(pick.unit_id)
        if unit is None or unit.product_id != product.pk or unit.kind != wanted_kind:
            raise StockError("UNIT_NOT_FOUND", 404)
        size = 1 if unit.kind == TraceKind.SERIAL else pick.quantity
        if size < 1 or size > unit.available:
            raise StockError("UNIT_NOT_AVAILABLE", 409, number=unit.number, max=unit.available)
        chosen.append((unit, size))
    if sum(size for _unit, size in chosen) != quantity:
        raise StockError("UNITS_COUNT_MISMATCH", 400, expected=quantity, given=sum(s for _u, s in chosen))
    return chosen


def allocate(shipment_line, chosen: list[tuple[TraceUnit, int]]) -> None:
    """Записать, какие единицы ушли строкой отгрузки; отгруженное целиком — «отгружен»."""
    for unit, size in chosen:
        TraceAllocation.objects.create(unit=unit, shipment_line=shipment_line, quantity=size)
        unit.shipped_quantity += size
        if unit.shipped_quantity >= unit.quantity:
            unit.status = TraceStatus.SHIPPED
        unit.save(update_fields=["shipped_quantity", "status"])


def present_unit_short(unit: TraceUnit) -> dict:
    return {
        "id": unit.pk,
        "kind": unit.kind,
        "number": unit.number,
        "expiry_date": unit.expiry_date,
        "available": unit.available,
    }


# ── поиск: откуда и куда ─────────────────────────────────────────────────────────────────────────────────────────────


def _deal_ref(deal) -> Optional[dict]:
    if deal is None:
        return None
    return {"id": deal.pk, "number": deal.number or None, "client_name": deal.company.name if deal.company_id else None}


def _origin(unit: TraceUnit) -> dict:
    line = unit.receipt_line
    receipt = line.receipt
    order = receipt.order
    brand = unit.product.brand
    return {
        "receipt_id": receipt.pk,
        "received_at": receipt.received_at,
        "supplier_doc": receipt.supplier_doc or None,
        "order_id": order.pk,
        "order_number": order.number,
        "supplier_name": order.supplier.name,
        "manufacturer": brand.name if brand is not None else None,
        "doc_number": line.conformity_doc_number or None,
        "doc_valid_until": line.conformity_doc_valid_until,
        "deal": _deal_ref(line.order_line.deal),
    }


def _destinations(unit: TraceUnit) -> list[dict]:
    return [
        {
            "shipment_id": a.shipment_line.shipment_id,
            "shipment_number": a.shipment_line.shipment.number,
            "shipped_at": a.shipment_line.shipment.shipped_at,
            "quantity": a.quantity,
            "deal": _deal_ref(a.shipment_line.shipment.deal),
        }
        for a in unit.allocations.all()
    ]


def search(user, query: str) -> list[dict]:
    """Единицы по серийному номеру или партии: точное совпадение первым, затем по части номера (от 2 знаков)."""
    require_staff(user)
    text = _clean(query)
    if len(text) < SEARCH_MIN:
        return []
    allocations = TraceAllocation.objects.select_related("shipment_line__shipment__deal__company")
    units = (
        TraceUnit.objects.filter(Q(number__iexact=text) | Q(number__icontains=text))
        .select_related(
            "product__brand",
            "receipt_line__receipt__order__supplier",
            "receipt_line__order_line__deal__company",
        )
        .prefetch_related(Prefetch("allocations", queryset=allocations))
        .order_by("number", "id")[:SEARCH_LIMIT]
    )
    rows = sorted(units, key=lambda u: (u.number.lower() != text.lower(), u.number, u.pk))
    return [
        {
            **present_unit_short(unit),
            "quantity": unit.quantity,
            "shipped_quantity": unit.shipped_quantity,
            "status": unit.status,
            "product": {
                "id": unit.product_id,
                "name": unit.product.name,
                "article": unit.product.manufacturer_part_number or unit.product.sku or "",
            },
            "origin": _origin(unit),
            "destinations": _destinations(unit),
        }
        for unit in rows
    ]
