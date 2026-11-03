"""Склад и закупки: схемы `Stock*`, `SupplierOrder*`, `PriceRequest*` из
packages/contracts/openapi/platform-bff.yaml (D2-2) и перевод ответов ERP (`/api/v1/stock/*`,
`inventory.services`, `supply.services`) в ответ Платформы.

BFF не решает: остаток, резерв, переходы статусов заказа, приёмку, отгрузку и права решает ERP
(`supply.manage`, `fulfillment.manage`). Здесь — номера заявок и заказов вместо внутренних id, пути
SPA, вырезание цен поставщиков по полям с ограничением (`platform-rbac.yaml` `restricted_fields`):
цену в заказе и сумму заказа видит группа `supplier_prices`, `cost_margin` или держатель зоны
товаров (`erp.calc.goods`) — те же правила, что в расчёте D2-1.
"""

import datetime as dt
from collections.abc import Collection, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.feeds.text import segment
from app.schemas_erp_calc import zones_of

DIGITS = r"^[0-9]+$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
DECIMAL = r"^-?[0-9]+(\.[0-9]+)?$"
OrderStatus = Literal["draft", "sent", "confirmed", "received", "cancelled"]
ReservationStatus = Literal["active", "released", "fulfilled"]
# ADR-0021 (L0-3): учёт единиц категории и вид единицы прослеживаемости.
TrackingClass = Literal["serial", "lot", "none"]
TraceKind = Literal["serial", "lot"]
Serial = Annotated[str, Field(max_length=100)]

# --- ответ BFF ---------------------------------------------------------------------------------


class StockRights(BaseModel):
    manage: bool
    ship: bool


class StockOrderRights(BaseModel):
    manage: bool
    ship: bool
    prices: bool


class StockRequestRef(BaseModel):
    number: str
    client: str | None
    path: str


class StockCell(BaseModel):
    cell: str | None
    on_hand: int


class StockRow(BaseModel):
    product_id: str
    name: str
    article: str
    unit: str
    on_hand: int
    reserved: int
    free: int
    incoming: int
    next_expected: dt.date | None
    cells: list[StockCell]


class StockBalanceList(BaseModel):
    items: list[StockRow]
    rights: StockRights


class StockTraceUnitRef(BaseModel):
    id: str
    kind: TraceKind
    number: str
    expiry_date: dt.date | None
    available: int


class StockReservation(BaseModel):
    id: str
    product_id: str
    product_name: str
    request: StockRequestRef
    line_id: str | None
    quantity: int
    shipped_quantity: int
    remaining: int
    status: ReservationStatus
    created_at: dt.datetime
    created_by: str | None
    tracking: TrackingClass
    units: list[StockTraceUnitRef]


class StockReservationList(BaseModel):
    items: list[StockReservation]


class StockIncomingOrder(BaseModel):
    number: str
    status: OrderStatus
    supplier: str
    expected_date: dt.date | None
    quantity_left: int
    path: str


class StockMovement(BaseModel):
    kind: Literal["receipt", "shipment", "adjustment"]
    quantity: int
    cell: str | None
    at: dt.datetime
    by: str | None
    note: str | None


class StockProduct(StockRow):
    reservations: list[StockReservation]
    incoming_orders: list[StockIncomingOrder]
    movements: list[StockMovement]
    rights: StockRights


class StockSupplierRef(BaseModel):
    id: str
    name: str
    email: str | None = None


class StockSupplierItem(BaseModel):
    id: str
    name: str
    inn: str | None
    email: str | None


class StockSupplierList(BaseModel):
    items: list[StockSupplierItem]


class SupplierOrderActions(BaseModel):
    edit: bool
    send: bool
    confirm: bool
    receive: bool
    cancel: bool


class SupplierOrderRow(BaseModel):
    number: str
    status: OrderStatus
    supplier: StockSupplierRef
    expected_date: dt.date | None
    overdue: bool
    days_overdue: int | None
    currency: str | None
    lines_count: int
    quantity: int
    received_quantity: int
    receipt_state: Literal["none", "partial", "full"]
    total: str | None
    requests: list[StockRequestRef]
    created_at: dt.datetime
    created_by: str | None
    actions: SupplierOrderActions
    path: str


class SupplierOrderList(BaseModel):
    items: list[SupplierOrderRow]
    rights: StockOrderRights


class SupplierOrderLineOffer(BaseModel):
    incoterms: str | None
    valid_until: dt.date | None
    expired: bool


class SupplierOrderLine(BaseModel):
    id: str
    position: int
    product_id: str | None
    name: str
    article: str
    unit: str
    quantity: int
    received_quantity: int
    unit_price: str | None
    line_total: str | None
    request: StockRequestRef | None
    line_id: str | None
    offer: SupplierOrderLineOffer | None
    tracking: TrackingClass
    requires_doc: bool


class StockDoneReceiptLine(BaseModel):
    name: str
    quantity: int
    cell: str | None
    units: list[str]
    expiry_date: dt.date | None
    doc_number: str | None
    doc_valid_until: dt.date | None


class SupplierOrderReceiptLine(StockDoneReceiptLine):
    order_line_id: str


class SupplierOrderReceipt(BaseModel):
    id: str
    received_at: dt.datetime
    received_by: str | None
    supplier_doc: str | None
    note: str | None
    lines: list[SupplierOrderReceiptLine]


class SupplierOrderLogEntry(BaseModel):
    kind: Literal[
        "created", "edited", "sent", "confirmed", "receipt", "received", "cancelled", "overdue"
    ]
    at: dt.datetime
    by: str | None
    detail: str | None


class SupplierOrderDetail(SupplierOrderRow):
    note: str
    sent_at: dt.datetime | None
    sent_to: str | None
    confirmed_at: dt.datetime | None
    received_at: dt.datetime | None
    cancelled_at: dt.datetime | None
    cancel_reason: str | None
    lines: list[SupplierOrderLine]
    receipts: list[SupplierOrderReceipt]
    log: list[SupplierOrderLogEntry]
    rights: StockOrderRights


class StockPendingReceiptLine(BaseModel):
    order_number: str
    order_path: str
    supplier: str
    expected_date: dt.date | None
    overdue: bool
    order_line_id: str
    name: str
    article: str
    unit: str
    quantity: int
    received_quantity: int
    request: StockRequestRef | None
    tracking: TrackingClass
    requires_doc: bool


class StockDoneReceipt(BaseModel):
    id: str
    order_number: str
    order_path: str
    supplier: str
    received_at: dt.datetime
    received_by: str | None
    supplier_doc: str | None
    quantity: int
    lines: list[StockDoneReceiptLine]


class StockReceipts(BaseModel):
    pending: list[StockPendingReceiptLine]
    done: list[StockDoneReceipt]
    rights: StockRights


class StockShipmentUnit(BaseModel):
    number: str
    quantity: int


class StockShipmentLine(BaseModel):
    product_id: str
    name: str
    quantity: int
    cell: str | None
    units: list[StockShipmentUnit]


class StockShipment(BaseModel):
    id: str
    number: str
    request: StockRequestRef
    tracking: str | None
    carrier: str | None
    note: str | None
    shipped_at: dt.datetime
    shipped_by: str | None
    lines: list[StockShipmentLine]


class StockShipmentList(BaseModel):
    items: list[StockShipment]
    rights: StockRights


class StockTraceProduct(BaseModel):
    id: str
    name: str
    article: str


class StockTraceOrigin(BaseModel):
    received_at: dt.datetime
    supplier_doc: str | None
    order_number: str
    order_path: str
    supplier: str
    manufacturer: str | None
    doc_number: str | None
    doc_valid_until: dt.date | None
    request: StockRequestRef | None


class StockTraceDestination(BaseModel):
    shipment_number: str
    shipped_at: dt.datetime
    quantity: int
    request: StockRequestRef


class StockTraceUnit(BaseModel):
    id: str
    kind: TraceKind
    number: str
    expiry_date: dt.date | None
    quantity: int
    shipped_quantity: int
    status: Literal["in_stock", "shipped"]
    product: StockTraceProduct
    origin: StockTraceOrigin
    destinations: list[StockTraceDestination]


class StockTraceList(BaseModel):
    items: list[StockTraceUnit]


class PriceRequestLine(BaseModel):
    line_id: str | None
    name: str
    article: str
    quantity: int
    unit: str


class PriceRequest(BaseModel):
    id: str
    supplier: StockSupplierRef
    request: str | None
    requested_at: dt.datetime
    requested_by: str | None
    to_email: str
    subject: str
    note: str | None
    status: Literal["sent", "failed"]
    error: str | None
    answered_at: dt.datetime | None
    answered_by: str | None
    answer_note: str | None
    lines: list[PriceRequestLine]


class PriceRequestList(BaseModel):
    items: list[PriceRequest]


# --- запросы -----------------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")


class StockAdjustIn(BaseModel):
    model_config = _STRICT

    product_id: str = Field(pattern=DIGITS, max_length=12)
    quantity: int = Field(ge=-10_000_000, le=10_000_000)
    cell: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=500)


class StockReserveIn(BaseModel):
    model_config = _STRICT

    quantity: int = Field(ge=1, le=10_000_000)


class SupplierOrderLineIn(BaseModel):
    model_config = _STRICT

    id: str | None = Field(default=None, pattern=DIGITS, max_length=12)
    product_id: str = Field(pattern=DIGITS, max_length=12)
    name: str | None = Field(default=None, max_length=500)
    article: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=32)
    quantity: int = Field(ge=1, le=10_000_000)
    unit_price: str | None = Field(default=None, pattern=DECIMAL, max_length=20)
    request: str | None = Field(default=None, min_length=1, max_length=40)
    line_id: str | None = Field(default=None, pattern=DIGITS, max_length=12)


class SupplierOrderCreate(BaseModel):
    model_config = _STRICT

    supplier_id: str = Field(pattern=DIGITS, max_length=12)
    expected_date: dt.date | None = None
    note: str | None = Field(default=None, max_length=5000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    lines: list[SupplierOrderLineIn] = Field(min_length=1, max_length=200)


class SupplierOrderFromRequest(BaseModel):
    model_config = _STRICT

    request: str = Field(min_length=1, max_length=40)
    supplier_id: str = Field(pattern=DIGITS, max_length=12)


class SupplierOrderPatch(BaseModel):
    model_config = _STRICT

    supplier_id: str | None = Field(default=None, pattern=DIGITS, max_length=12)
    expected_date: dt.date | None = None
    note: str | None = Field(default=None, max_length=5000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    lines: list[SupplierOrderLineIn] | None = Field(default=None, min_length=1, max_length=200)


class SupplierOrderSendIn(BaseModel):
    model_config = _STRICT

    to_email: str | None = Field(default=None, pattern=EMAIL, max_length=254)


class SupplierOrderConfirmIn(BaseModel):
    model_config = _STRICT

    expected_date: dt.date | None = None


class SupplierOrderCancelIn(BaseModel):
    model_config = _STRICT

    reason: str | None = Field(default=None, max_length=500)


class ReceiptLineIn(BaseModel):
    model_config = _STRICT

    order_line_id: str = Field(pattern=DIGITS, max_length=12)
    quantity: int = Field(ge=1, le=10_000_000)
    cell: str | None = Field(default=None, max_length=32)
    # ADR-0021: по классу категории; обязательность и число серийных проверяет ERP.
    serials: list[Serial] | None = Field(default=None, max_length=1000)
    lot: str | None = Field(default=None, max_length=100)
    expiry_date: dt.date | None = None
    doc_number: str | None = Field(default=None, max_length=100)
    doc_valid_until: dt.date | None = None


class SupplierOrderReceiptIn(BaseModel):
    model_config = _STRICT

    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=200)
    supplier_doc: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class ShipUnitIn(BaseModel):
    model_config = _STRICT

    unit_id: str = Field(pattern=DIGITS, max_length=12)
    quantity: int = Field(default=1, ge=1, le=10_000_000)


class ShipLineIn(BaseModel):
    model_config = _STRICT

    reservation_id: str = Field(pattern=DIGITS, max_length=12)
    quantity: int = Field(ge=1, le=10_000_000)
    units: list[ShipUnitIn] | None = Field(default=None, max_length=1000)


class StockShipIn(BaseModel):
    model_config = _STRICT

    request: str = Field(min_length=1, max_length=40)
    lines: list[ShipLineIn] = Field(min_length=1, max_length=100)
    tracking: str | None = Field(default=None, max_length=128)
    carrier: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=500)


class PriceRequestIn(BaseModel):
    model_config = _STRICT

    supplier_id: str = Field(pattern=DIGITS, max_length=12)
    line_ids: list[Annotated[str, Field(pattern=DIGITS, max_length=12)]] = Field(
        min_length=1, max_length=100
    )
    note: str | None = Field(default=None, max_length=1000)
    to_email: str | None = Field(default=None, pattern=EMAIL, max_length=254)


class PriceRequestAnswerIn(BaseModel):
    model_config = _STRICT

    note: str | None = Field(default=None, max_length=1000)


# --- перевод ответов ERP -----------------------------------------------------------------------


def prices_visible(fields: Collection[str], access: Mapping[str, str]) -> bool:
    """Цены поставщиков: `supplier_prices`, `cost_margin` или зона товаров (как в расчёте)."""
    return "supplier_prices" in fields or "cost_margin" in fields or "goods" in zones_of(access)


def _id(value: Any) -> str | None:
    return None if value is None else str(value)


def stock_path(number: str) -> str:
    return f"/erp/stock/{segment(number)}"


def request_ref(raw: Mapping[str, Any] | None) -> StockRequestRef | None:
    """Заявка или проект: ЗВ — расчёт (рабочее место снабжения), ПР — проект в EDS."""
    if not isinstance(raw, Mapping) or not raw.get("number"):
        return None
    number = str(raw["number"])
    path = (
        f"/eds/projects/{segment(number)}"
        if number.startswith("ПР")
        else f"/erp/calc/{segment(number)}"
    )
    return StockRequestRef(number=number, client=raw.get("client_name"), path=path)


def _require_ref(raw: Mapping[str, Any] | None) -> StockRequestRef:
    ref = request_ref(raw)
    if ref is None:
        # Заявка без номера (старые сделки) в складских экранах не встречается.
        number = f"#{raw['id']}" if isinstance(raw, Mapping) and raw.get("id") else "—"
        return StockRequestRef(
            number=number,
            client=raw.get("client_name") if isinstance(raw, Mapping) else None,
            path="/erp/requests",
        )
    return ref


def to_row(raw: Mapping[str, Any]) -> StockRow:
    return StockRow(
        product_id=str(raw["product_id"]),
        name=raw["name"],
        article=raw.get("article") or "",
        unit=raw.get("unit") or "",
        on_hand=raw["on_hand"],
        reserved=raw["reserved"],
        free=raw["free"],
        incoming=raw["incoming"],
        next_expected=raw.get("next_expected"),
        cells=[StockCell(cell=c.get("cell"), on_hand=c["on_hand"]) for c in raw.get("cells") or []],
    )


def to_rights(raw: Mapping[str, Any]) -> StockRights:
    return StockRights(manage=bool(raw.get("manage")), ship=bool(raw.get("ship")))


def to_balances(raw: Mapping[str, Any]) -> StockBalanceList:
    return StockBalanceList(
        items=[to_row(row) for row in raw.get("results", [])],
        rights=to_rights(raw.get("rights") or {}),
    )


def to_reservation(raw: Mapping[str, Any]) -> StockReservation:
    return StockReservation(
        id=str(raw["id"]),
        product_id=str(raw["product_id"]),
        product_name=raw["product_name"],
        request=_require_ref(raw.get("deal")),
        line_id=_id(raw.get("quote_item_id")),
        quantity=raw["quantity"],
        shipped_quantity=raw["shipped_quantity"],
        remaining=raw["remaining"],
        status=raw["status"],
        created_at=raw["created_at"],
        created_by=raw.get("created_by_name"),
        tracking=raw.get("tracking") or "none",
        units=[
            StockTraceUnitRef(
                id=str(u["id"]),
                kind=u["kind"],
                number=u["number"],
                expiry_date=u.get("expiry_date"),
                available=u["available"],
            )
            for u in raw.get("units") or []
        ],
    )


def _offer(raw: Any) -> SupplierOrderLineOffer | None:
    if not isinstance(raw, Mapping):
        return None
    return SupplierOrderLineOffer(
        incoterms=raw.get("incoterms"),
        valid_until=raw.get("valid_until"),
        expired=bool(raw.get("expired")),
    )


def _receipt_line(rl: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": rl["name"],
        "quantity": rl["quantity"],
        "cell": rl.get("cell"),
        "units": list(rl.get("units") or []),
        "expiry_date": rl.get("expiry_date"),
        "doc_number": rl.get("doc_number"),
        "doc_valid_until": rl.get("doc_valid_until"),
    }


def to_product(raw: Mapping[str, Any]) -> StockProduct:
    base = to_row(raw)
    return StockProduct(
        **base.model_dump(),
        reservations=[to_reservation(r) for r in raw.get("reservations") or []],
        incoming_orders=[
            StockIncomingOrder(
                number=o["number"],
                status=o["status"],
                supplier=o["supplier_name"],
                expected_date=o.get("expected_date"),
                quantity_left=o["quantity_left"],
                path=stock_path(o["number"]),
            )
            for o in raw.get("incoming_orders") or []
        ],
        movements=[
            StockMovement(
                kind=m["kind"],
                quantity=m["quantity"],
                cell=m.get("cell"),
                at=m["at"],
                by=m.get("by_name"),
                note=m.get("note"),
            )
            for m in raw.get("movements") or []
        ],
        rights=to_rights(raw.get("rights") or {}),
    )


def to_suppliers(raw: Mapping[str, Any]) -> StockSupplierList:
    return StockSupplierList(
        items=[
            StockSupplierItem(
                id=str(s["id"]), name=s["name"], inn=s.get("inn"), email=s.get("email")
            )
            for s in raw.get("results", [])
        ]
    )


def _order_rights(raw: Mapping[str, Any], prices: bool) -> StockOrderRights:
    rights = raw or {}
    return StockOrderRights(
        manage=bool(rights.get("manage")),
        ship=bool(rights.get("ship")),
        prices=bool(rights.get("prices")) and prices,
    )


def _row_data(raw: Mapping[str, Any], prices: bool) -> dict[str, Any]:
    supplier = raw["supplier"]
    return {
        "number": raw["number"],
        "status": raw["status"],
        "supplier": StockSupplierRef(
            id=str(supplier["id"]), name=supplier["name"], email=supplier.get("email")
        ),
        "expected_date": raw.get("expected_date"),
        "overdue": bool(raw.get("overdue")),
        "days_overdue": raw.get("days_overdue"),
        "currency": raw.get("currency"),
        "lines_count": raw["lines_count"],
        "quantity": raw["quantity"],
        "received_quantity": raw["received_quantity"],
        "receipt_state": raw["receipt_state"],
        "total": raw.get("total") if prices else None,
        "requests": [
            r for r in (request_ref(p) for p in raw.get("projects") or []) if r is not None
        ],
        "created_at": raw["created_at"],
        "created_by": raw.get("created_by_name"),
        "actions": SupplierOrderActions(**raw["actions"]),
        "path": stock_path(raw["number"]),
    }


def to_order_row(raw: Mapping[str, Any], prices: bool) -> SupplierOrderRow:
    return SupplierOrderRow(**_row_data(raw, prices))


def to_order_list(raw: Mapping[str, Any], prices: bool) -> SupplierOrderList:
    return SupplierOrderList(
        items=[to_order_row(row, prices) for row in raw.get("results", [])],
        rights=_order_rights(raw.get("rights") or {}, prices),
    )


def to_order(raw: Mapping[str, Any], prices: bool) -> SupplierOrderDetail:
    return SupplierOrderDetail(
        **_row_data(raw, prices),
        note=raw.get("note") or "",
        sent_at=raw.get("sent_at"),
        sent_to=raw.get("sent_to"),
        confirmed_at=raw.get("confirmed_at"),
        received_at=raw.get("received_at"),
        cancelled_at=raw.get("cancelled_at"),
        cancel_reason=raw.get("cancel_reason"),
        lines=[
            SupplierOrderLine(
                id=str(line["id"]),
                position=line["position"],
                product_id=_id(line.get("product_id")),
                name=line["name"],
                article=line.get("article") or "",
                unit=line.get("unit") or "",
                quantity=line["quantity"],
                received_quantity=line["received_quantity"],
                unit_price=line.get("unit_price") if prices else None,
                line_total=line.get("line_total") if prices else None,
                request=request_ref(line.get("deal")),
                line_id=_id(line.get("quote_item_id")),
                offer=_offer(line.get("offer")),
                tracking=line.get("tracking") or "none",
                requires_doc=bool(line.get("requires_doc")),
            )
            for line in raw.get("lines") or []
        ],
        receipts=[
            SupplierOrderReceipt(
                id=str(r["id"]),
                received_at=r["received_at"],
                received_by=r.get("received_by_name"),
                supplier_doc=r.get("supplier_doc"),
                note=r.get("note"),
                lines=[
                    SupplierOrderReceiptLine(
                        order_line_id=str(rl["order_line_id"]), **_receipt_line(rl)
                    )
                    for rl in r.get("lines") or []
                ],
            )
            for r in raw.get("receipts") or []
        ],
        log=[
            SupplierOrderLogEntry(
                kind=e["kind"], at=e["at"], by=e.get("by_name"), detail=e.get("detail")
            )
            for e in raw.get("log") or []
        ],
        rights=_order_rights(raw.get("rights") or {}, prices),
    )


def to_receipts(raw: Mapping[str, Any]) -> StockReceipts:
    return StockReceipts(
        pending=[
            StockPendingReceiptLine(
                order_number=p["order_number"],
                order_path=stock_path(p["order_number"]),
                supplier=p["supplier_name"],
                expected_date=p.get("expected_date"),
                overdue=bool(p.get("overdue")),
                order_line_id=str(p["order_line_id"]),
                name=p["name"],
                article=p.get("article") or "",
                unit=p.get("unit") or "",
                quantity=p["quantity"],
                received_quantity=p["received_quantity"],
                request=request_ref(p.get("deal")),
                tracking=p.get("tracking") or "none",
                requires_doc=bool(p.get("requires_doc")),
            )
            for p in raw.get("pending") or []
        ],
        done=[
            StockDoneReceipt(
                id=str(d["id"]),
                order_number=d["order_number"],
                order_path=stock_path(d["order_number"]),
                supplier=d["supplier_name"],
                received_at=d["received_at"],
                received_by=d.get("received_by_name"),
                supplier_doc=d.get("supplier_doc"),
                quantity=d["quantity"],
                lines=[StockDoneReceiptLine(**_receipt_line(x)) for x in d.get("lines") or []],
            )
            for d in raw.get("done") or []
        ],
        rights=to_rights(raw.get("rights") or {}),
    )


def to_shipment(raw: Mapping[str, Any]) -> StockShipment:
    return StockShipment(
        id=str(raw["id"]),
        number=raw["number"],
        request=_require_ref(raw.get("deal")),
        tracking=raw.get("tracking"),
        carrier=raw.get("carrier"),
        note=raw.get("note"),
        shipped_at=raw["shipped_at"],
        shipped_by=raw.get("shipped_by_name"),
        lines=[
            StockShipmentLine(
                product_id=str(x["product_id"]),
                name=x["name"],
                quantity=x["quantity"],
                cell=x.get("cell"),
                units=[
                    StockShipmentUnit(number=u["number"], quantity=u["quantity"])
                    for u in x.get("units") or []
                ],
            )
            for x in raw.get("lines") or []
        ],
    )


def to_trace(raw: Mapping[str, Any]) -> StockTraceList:
    """Поиск по серийному или партии: номера заказов и проектов вместо внутренних id."""
    items = []
    for u in raw.get("results") or []:
        origin = u["origin"]
        items.append(
            StockTraceUnit(
                id=str(u["id"]),
                kind=u["kind"],
                number=u["number"],
                expiry_date=u.get("expiry_date"),
                quantity=u["quantity"],
                shipped_quantity=u["shipped_quantity"],
                status=u["status"],
                product=StockTraceProduct(
                    id=str(u["product"]["id"]),
                    name=u["product"]["name"],
                    article=u["product"].get("article") or "",
                ),
                origin=StockTraceOrigin(
                    received_at=origin["received_at"],
                    supplier_doc=origin.get("supplier_doc"),
                    order_number=origin["order_number"],
                    order_path=stock_path(origin["order_number"]),
                    supplier=origin["supplier_name"],
                    manufacturer=origin.get("manufacturer"),
                    doc_number=origin.get("doc_number"),
                    doc_valid_until=origin.get("doc_valid_until"),
                    request=request_ref(origin.get("deal")),
                ),
                destinations=[
                    StockTraceDestination(
                        shipment_number=d["shipment_number"],
                        shipped_at=d["shipped_at"],
                        quantity=d["quantity"],
                        request=_require_ref(d.get("deal")),
                    )
                    for d in u.get("destinations") or []
                ],
            )
        )
    return StockTraceList(items=items)


def to_shipments(raw: Mapping[str, Any]) -> StockShipmentList:
    return StockShipmentList(
        items=[to_shipment(s) for s in raw.get("results", [])],
        rights=to_rights(raw.get("rights") or {}),
    )


def to_price_request(raw: Mapping[str, Any]) -> PriceRequest:
    supplier = raw["supplier"]
    return PriceRequest(
        id=str(raw["id"]),
        supplier=StockSupplierRef(id=str(supplier["id"]), name=supplier["name"]),
        request=raw.get("deal_number"),
        requested_at=raw["requested_at"],
        requested_by=raw.get("requested_by_name"),
        to_email=raw["to_email"],
        subject=raw["subject"],
        note=raw.get("note"),
        status=raw["status"],
        error=raw.get("error"),
        answered_at=raw.get("answered_at"),
        answered_by=raw.get("answered_by_name"),
        answer_note=raw.get("answer_note"),
        lines=[
            PriceRequestLine(
                line_id=_id(x.get("quote_item_id")),
                name=x["name"],
                article=x.get("article") or "",
                quantity=x["quantity"],
                unit=x.get("unit") or "",
            )
            for x in raw.get("lines") or []
        ],
    )
