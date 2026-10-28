"""Операции склада (D2-2, SPEC-v3 §7.4 «Склад»): остатки, резервы, корректировки, отгрузки по проектам.

Правила (одно место, ORCHESTRATOR §3: код решает, не модель):

* Остаток ведётся по ячейкам (`StockBalance`) вместе с журналом движений (`StockMovement`) в одной транзакции. Остаток не
  уходит ниже нуля (`PositiveIntegerField`) и ниже суммы резервов (409 `BELOW_RESERVED`).
* **Свободный остаток** = остаток − остаток резервов действующих проектов (заявки, проигранные в CLOSED_LOST, резерв не
  держат — читается при подсчёте, без хуков в стадиях). Резерв строки расчёта один; повторное «Зарезервировать» меняет
  количество (не больше свободного остатка плюс уже удерживаемого этой строкой, 409 `NOT_ENOUGH_STOCK`).
* Резерв, отгрузка, корректировка и приёмка одного товара идут под блокировкой строки товара (`select_for_update` на
  `catalog.Product`, товары блокируются по возрастанию id): две вкладки не отдадут один остаток двум проектам.
* **Отгрузка** — по резервам одной заявки, после подписания договора (есть `Fulfillment`, иначе 409
  `FULFILLMENT_NOT_READY`): остаток и резерв уменьшаются, выдаётся внутренняя накладная ОТГ-ГГГГ-NNN. Когда весь товар
  последнего одобренного КП отгружен, исполнение сделки переводится в «Отгружено» существующим
  `crm.services.fulfillment.update_fulfillment_status` (накладная DN, события шины, карточки поставки клиента) — второго
  пути исполнения здесь нет. Частичная отгрузка карточки поставки клиента не меняет (хвост B-D22-1).

Ошибки — `StockError(code, status)`; вьюхи отдают `{"detail": code}`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from inventory.access import StockError, person_name, require_fulfillment, require_staff, require_supply
from inventory.models import (
    DocumentCounter,
    MovementKind,
    Reservation,
    ReservationStatus,
    Shipment,
    ShipmentLine,
    StockBalance,
    StockMovement,
    Warehouse,
)

from catalog.models import Product

logger = logging.getLogger(__name__)

MAX_CELL = 32
LOST_STAGE = "CLOSED_LOST"
CLOSED_STAGES = ("CLOSED_LOST", "CLOSED_WON")


# ── справочные вещи ────────────────────────────────────────────────────────────────────────────────────────────────


def default_warehouse() -> Warehouse:
    """Основной склад; заводится при первом обращении (одна строка с `is_default`)."""
    warehouse = Warehouse.objects.filter(is_default=True).first()
    if warehouse is None:
        warehouse, _created = Warehouse.objects.get_or_create(
            code="MAIN", defaults={"name": "Основной склад", "is_default": True}
        )
    return warehouse


@transaction.atomic
def next_number(kind: str, prefix: str) -> tuple[str, int, int]:
    """(номер, год, NNN) из счётчика вида и года под блокировкой: без пропусков, откат транзакции возвращает номер.
    Вызывать внутри транзакции."""
    year = timezone.localdate().year
    DocumentCounter.objects.bulk_create([DocumentCounter(kind=kind, year=year)], ignore_conflicts=True)
    counter = DocumentCounter.objects.select_for_update().get(kind=kind, year=year)
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return f"{prefix}-{year:04d}-{counter.last_value:03d}", year, counter.last_value


@transaction.atomic
def lock_products(product_ids: Iterable[int]) -> None:
    """Блокировка товаров по возрастанию id (один порядок у всех — нет взаимной блокировки). Только в транзакции."""
    ids = sorted({pid for pid in product_ids if pid})
    if ids:
        list(Product.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))


def active_reservations():
    """Действующие резервы: не снятые, не отгруженные целиком, по заявкам, которые не проиграны."""
    return Reservation.objects.filter(status=ReservationStatus.ACTIVE).exclude(deal__stage__code=LOST_STAGE)


# ── доступность ────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Availability:
    on_hand: int = 0
    reserved: int = 0
    tracked: bool = False
    cells: list[tuple[str, int]] = field(default_factory=list)

    @property
    def free(self) -> int:
        return max(self.on_hand - self.reserved, 0)

    @property
    def main_cell(self) -> Optional[str]:
        """Ячейка с наибольшим остатком; без ячейки — None."""
        for cell, quantity in sorted(self.cells, key=lambda row: -row[1]):
            if quantity > 0 and cell:
                return cell
        return None


def availability(product_ids: Iterable[int]) -> dict[int, Availability]:
    """Остаток, резерв и ячейки по товарам одним проходом. `tracked` — по товару ведётся учёт движений (есть строка
    остатка, пусть нулевая); без него расчёт D2-1 берёт наличие из своего предложения (прежнее поведение)."""
    ids = [pid for pid in set(product_ids) if pid]
    found: dict[int, Availability] = {pid: Availability() for pid in ids}
    if not ids:
        return found
    for row in StockBalance.objects.filter(product_id__in=ids).values("product_id", "cell", "on_hand"):
        info = found[row["product_id"]]
        info.tracked = True
        info.on_hand += row["on_hand"]
        info.cells.append((row["cell"], row["on_hand"]))
    reserved = (
        active_reservations()
        .filter(product_id__in=ids)
        .values("product_id")
        .annotate(total=Sum(F("quantity") - F("shipped_quantity")))
    )
    for row in reserved:
        found[row["product_id"]].reserved = row["total"] or 0
    return found


def reserved_by_item(item_ids: Iterable[int]) -> dict[int, int]:
    """Сколько удерживается за строками расчёта (остаток резерва)."""
    ids = [i for i in set(item_ids) if i]
    if not ids:
        return {}
    rows = active_reservations().filter(quote_item_id__in=ids).values("quote_item_id", "quantity", "shipped_quantity")
    return {row["quote_item_id"]: row["quantity"] - row["shipped_quantity"] for row in rows}


# ── движения ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _clean_cell(cell: Optional[str]) -> str:
    value = (cell or "").strip()
    if len(value) > MAX_CELL:
        raise StockError("CELL_TOO_LONG", 400)
    return value


@transaction.atomic
def add_stock(
    product_id: int,
    quantity: int,
    *,
    kind: str,
    user,
    cell: str = "",
    warehouse: Optional[Warehouse] = None,
    source_id: Optional[int] = None,
    note: str = "",
) -> StockBalance:
    """Приход (quantity > 0) или расход (< 0) в ячейке + запись журнала. Товар уже заблокирован вызывающим."""
    warehouse = warehouse or default_warehouse()
    cell = _clean_cell(cell)
    balance, _created = StockBalance.objects.select_for_update().get_or_create(
        product_id=product_id, warehouse=warehouse, cell=cell
    )
    if balance.on_hand + quantity < 0:
        raise StockError("NOT_ENOUGH_STOCK", 409, free=balance.on_hand)
    balance.on_hand += quantity
    balance.save(update_fields=["on_hand", "updated_at"])
    StockMovement.objects.create(
        product_id=product_id,
        warehouse=warehouse,
        cell=cell,
        quantity=quantity,
        kind=kind,
        source_id=source_id,
        note=note[:500],
        created_by=user if getattr(user, "pk", None) else None,
    )
    return balance


def _product_or_404(product_id: int) -> Product:
    product = Product.objects.select_related("domain_type").filter(pk=product_id).first()
    if product is None:
        raise StockError("PRODUCT_NOT_FOUND", 404)
    if product.is_service:
        raise StockError("SERVICE_NOT_STOCKED", 409)
    return product


@transaction.atomic
def adjust(user, product_id: int, quantity: int, *, cell: str = "", note: str = "") -> dict:
    """Корректировка остатка вручную: «Оприходовать» (плюс) или «Списать» (минус) в ячейке; начальные остатки, итоги
    инвентаризации. Ниже нуля и ниже суммы резервов остаток не уходит."""
    require_supply(user)
    if not quantity:
        raise StockError("QUANTITY_REQUIRED", 400)
    _product_or_404(product_id)
    lock_products([product_id])
    state = availability([product_id])[product_id]
    if quantity < 0 and state.on_hand + quantity < 0:
        raise StockError("NOT_ENOUGH_STOCK", 409, free=state.on_hand)
    if quantity < 0 and state.on_hand + quantity < state.reserved:
        raise StockError("BELOW_RESERVED", 409, reserved=state.reserved, on_hand=state.on_hand)
    add_stock(product_id, quantity, kind=MovementKind.ADJUSTMENT, user=user, cell=cell, note=note)
    return {"product_id": product_id}


# ── резервы ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _item_for_reservation(deal_id: int, item_id: int):
    from sales.models import Quote, QuoteItem

    item = (
        QuoteItem.objects.billable()
        .select_related("product__domain_type", "quote__deal__stage")
        .filter(pk=item_id, quote__deal_id=deal_id)
        .first()
    )
    if item is None:
        raise StockError("LINE_NOT_FOUND", 404)
    latest = Quote.objects.filter(deal_id=deal_id).order_by("-version").values_list("pk", flat=True).first()
    if item.quote_id != latest:
        raise StockError("LINE_NOT_ACTUAL", 409)
    return item


@transaction.atomic
def reserve(user, deal_id: int, item_id: int, quantity: int) -> Reservation:
    """Зарезервировать товар под строку расчёта (или изменить уже удерживаемое количество)."""
    require_supply(user)
    item = _item_for_reservation(deal_id, item_id)
    stage = item.quote.deal.stage.code if item.quote.deal.stage_id else ""
    if stage in CLOSED_STAGES:
        raise StockError("DEAL_CLOSED", 409)
    if not item.product_id:
        raise StockError("PRODUCT_REQUIRED", 409)
    product = item.product
    if product.is_service:
        raise StockError("SERVICE_NOT_STOCKED", 409)
    if quantity < 1 or quantity > item.quantity:
        raise StockError("QUANTITY_OUT_OF_RANGE", 400, max=item.quantity)
    lock_products([product.pk])
    current = Reservation.objects.select_for_update().filter(quote_item=item, status=ReservationStatus.ACTIVE).first()
    state = availability([product.pk])[product.pk]
    held = current.remaining if current else 0
    free_for_line = state.free + held
    if quantity > free_for_line:
        raise StockError("NOT_ENOUGH_STOCK", 409, free=free_for_line)
    if current is None:
        reservation = Reservation.objects.create(
            product=product,
            deal_id=deal_id,
            quote_item=item,
            quantity=quantity,
            created_by=user if getattr(user, "pk", None) else None,
        )
    else:
        if quantity < current.shipped_quantity:
            raise StockError("BELOW_SHIPPED", 409, shipped=current.shipped_quantity)
        current.quantity = quantity
        current.save(update_fields=["quantity"])
        reservation = current
    _log_deal(
        item.quote.deal,
        user,
        "Резерв на складе",
        f"{product.name}: {quantity}",
        "stock.reserved",
        {"product": product.name, "quantity": quantity},
    )
    return reservation


@transaction.atomic
def release(user, reservation_id: int) -> Reservation:
    """Снять резерв: ещё не отгруженное возвращается в свободный остаток; отгруженная часть остаётся фактом."""
    require_supply(user)
    reservation = (
        Reservation.objects.select_for_update().select_related("deal", "product").filter(pk=reservation_id).first()
    )
    if reservation is None:
        raise StockError("RESERVATION_NOT_FOUND", 404)
    if reservation.status != ReservationStatus.ACTIVE:
        raise StockError("RESERVATION_NOT_ACTIVE", 409)
    reservation.released_at = timezone.now()
    reservation.released_by = user if getattr(user, "pk", None) else None
    if reservation.shipped_quantity:
        reservation.quantity = reservation.shipped_quantity
        reservation.status = ReservationStatus.FULFILLED
    else:
        reservation.status = ReservationStatus.RELEASED
    reservation.save(update_fields=["quantity", "status", "released_at", "released_by"])
    _log_deal(
        reservation.deal,
        user,
        "Резерв снят",
        reservation.product.name,
        "stock.released",
        {"product": reservation.product.name},
    )
    return reservation


@transaction.atomic
def sync_reservation(item) -> None:
    """Строку расчёта поменяли: резерв другого товара снимается, резерв больше нового количества урезается (отгруженное
    остаётся фактом). Вызывает `crm.services.calculation.update_line` внутри своей транзакции."""
    for reservation in Reservation.objects.select_for_update().filter(quote_item=item, status=ReservationStatus.ACTIVE):
        if reservation.product_id != item.product_id:
            reservation.released_at = timezone.now()
            if reservation.shipped_quantity:
                reservation.quantity = reservation.shipped_quantity
                reservation.status = ReservationStatus.FULFILLED
            else:
                reservation.status = ReservationStatus.RELEASED
            reservation.save(update_fields=["quantity", "status", "released_at"])
        elif reservation.quantity > item.quantity:
            reservation.quantity = max(item.quantity, reservation.shipped_quantity, 1)
            if reservation.shipped_quantity >= reservation.quantity:
                reservation.status = ReservationStatus.FULFILLED
            reservation.save(update_fields=["quantity", "status"])


@transaction.atomic
def release_for_item(item) -> None:
    """Строка расчёта удаляется — её резерв снимается (вызывает `crm.services.calculation.delete_line`)."""
    for reservation in Reservation.objects.select_for_update().filter(quote_item=item, status=ReservationStatus.ACTIVE):
        reservation.released_at = timezone.now()
        if reservation.shipped_quantity:
            reservation.quantity = reservation.shipped_quantity
            reservation.status = ReservationStatus.FULFILLED
        else:
            reservation.status = ReservationStatus.RELEASED
        reservation.save(update_fields=["quantity", "status", "released_at"])


# ── отгрузки ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class ShipInput:
    reservation_id: int
    quantity: int


def _take_from_cells(product_id: int, quantity: int, user, shipment_id: int) -> list[tuple[Warehouse, str, int]]:
    """Списать `quantity` с ячеек товара (сначала самые полные); вернуть, откуда сколько взято."""
    taken: list[tuple[Warehouse, str, int]] = []
    left = quantity
    balances = (
        StockBalance.objects.select_for_update()
        .select_related("warehouse")
        .filter(product_id=product_id, on_hand__gt=0)
        .order_by("-on_hand", "id")
    )
    for balance in balances:
        if left <= 0:
            break
        part = min(balance.on_hand, left)
        add_stock(
            product_id,
            -part,
            kind=MovementKind.SHIPMENT,
            user=user,
            cell=balance.cell,
            warehouse=balance.warehouse,
            source_id=shipment_id,
        )
        taken.append((balance.warehouse, balance.cell, part))
        left -= part
    if left > 0:
        raise StockError("NOT_ENOUGH_STOCK", 409)
    return taken


@transaction.atomic
def ship(
    user,
    deal_id: int,
    lines: list[ShipInput],
    *,
    tracking: str = "",
    carrier: str = "",
    note: str = "",
) -> Shipment:
    """Отгрузка со склада по резервам одной заявки. Остаток и резерв уменьшаются, выдаётся накладная ОТГ-ГГГГ-NNN."""
    from sales.models import Deal, Fulfillment

    require_fulfillment(user)
    if not lines:
        raise StockError("LINES_REQUIRED", 400)
    if len({line.reservation_id for line in lines}) != len(lines):
        raise StockError("DUPLICATE_LINE", 400)
    deal = Deal.objects.select_related("stage").filter(pk=deal_id).first()
    if deal is None:
        raise StockError("DEAL_NOT_FOUND", 404)
    if not Fulfillment.objects.filter(deal_id=deal_id).exists():
        raise StockError("FULFILLMENT_NOT_READY", 409)
    reservations = {
        r.pk: r
        for r in Reservation.objects.select_for_update(of=("self",))
        .select_related("product", "quote_item")
        .filter(pk__in=[line.reservation_id for line in lines])
    }
    for line in lines:
        reservation = reservations.get(line.reservation_id)
        # Объектная проверка: резерв чужой заявки не отгружается через эту.
        if reservation is None or reservation.deal_id != deal_id:
            raise StockError("RESERVATION_NOT_FOUND", 404)
    lock_products([r.product_id for r in reservations.values()])
    number, year, seq = next_number("SHP", "ОТГ")
    shipment = Shipment.objects.create(
        number=number,
        number_year=year,
        number_seq=seq,
        deal=deal,
        tracking=tracking.strip()[:128],
        carrier=carrier.strip()[:128],
        note=note.strip()[:500],
        shipped_by=user if getattr(user, "pk", None) else None,
    )
    for line in lines:
        reservation = Reservation.objects.select_for_update().get(pk=line.reservation_id)  # перечитано под блокировкой
        if reservation.status != ReservationStatus.ACTIVE:
            raise StockError("RESERVATION_NOT_ACTIVE", 409)
        if line.quantity < 1 or line.quantity > reservation.remaining:
            raise StockError("QUANTITY_OUT_OF_RANGE", 400, max=reservation.remaining)
        for warehouse, cell, part in _take_from_cells(reservation.product_id, line.quantity, user, shipment.pk):
            ShipmentLine.objects.create(
                shipment=shipment,
                reservation=reservation,
                product_id=reservation.product_id,
                quote_item_id=reservation.quote_item_id,
                quantity=part,
                warehouse=warehouse,
                cell=cell,
            )
        reservation.shipped_quantity += line.quantity
        if reservation.shipped_quantity >= reservation.quantity:
            reservation.status = ReservationStatus.FULFILLED
        reservation.save(update_fields=["shipped_quantity", "status"])
    _log_deal(
        deal,
        user,
        "Отгрузка со склада",
        f"{number}: {sum(line.quantity for line in lines)} шт.",
        "stock.shipped",
        {"number": number},
    )
    _complete_fulfillment_if_shipped(deal, shipment, user)
    return shipment


def goods_fully_shipped(deal) -> bool:
    """Весь товар последнего одобренного КП отгружен со склада: каждой строке-товару хватает отгруженного количества.
    Строка товара без карточки каталога (на склад не заводится) отгрузку «полной» не делает."""
    from sales.models import Quote

    from crm.constants import QuoteStatusCode
    from crm.services.calculation import zone_of

    quote = Quote.objects.filter(deal=deal, status__code=QuoteStatusCode.APPROVED).order_by("-version").first()
    if quote is None:
        return False
    items = list(quote.items.billable().select_related("product__domain_type", "calc"))
    goods = [item for item in items if zone_of(item) == "goods"]
    if not goods:
        return False
    shipped = {
        row["quote_item_id"]: row["total"]
        for row in ShipmentLine.objects.filter(quote_item__in=goods)
        .values("quote_item_id")
        .annotate(total=Sum("quantity"))
    }
    return all(item.product_id and shipped.get(item.pk, 0) >= item.quantity for item in goods)


def _complete_fulfillment_if_shipped(deal, shipment: Shipment, user) -> None:
    """Весь товар ушёл — исполнение сделки «Отгружено» тем же путём, что и ручная отметка (накладная DN, шина)."""
    from sales.models import Fulfillment

    from crm.constants import FulfillmentStatusCode
    from crm.services.fulfillment import update_fulfillment_status

    if not goods_fully_shipped(deal):
        return
    fulfillment = Fulfillment.objects.select_related("status").filter(deal=deal).first()
    if (
        fulfillment is None
        or (fulfillment.status.code if fulfillment.status_id else None) != FulfillmentStatusCode.PENDING
    ):
        return
    extra: dict[str, Any] = {}
    if shipment.tracking:
        extra["tracking_number"] = shipment.tracking
    if shipment.carrier:
        extra["carrier"] = shipment.carrier
    _obj, error = update_fulfillment_status(deal.pk, user, FulfillmentStatusCode.SHIPPED, **extra)
    if error:
        logger.warning("Исполнение сделки %s не переведено в «Отгружено» после %s: %s", deal.pk, shipment.number, error)


def _log_deal(deal, user, action: str, detail: str, event_code: str, params: dict) -> None:
    from sales.models import ActivityLog

    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=user if getattr(user, "pk", None) else None,
        level="INFO",
        entity_type="deal",
        entity_id=deal.pk,
        deal=deal,
        company_id=deal.company_id,
        event_code=event_code,
        event_params=params,
    )


__all__ = [
    "Availability",
    "ShipInput",
    "StockError",
    "active_reservations",
    "add_stock",
    "adjust",
    "availability",
    "default_warehouse",
    "goods_fully_shipped",
    "lock_products",
    "next_number",
    "person_name",
    "release",
    "release_for_item",
    "sync_reservation",
    "require_staff",
    "reserve",
    "reserved_by_item",
    "ship",
]
