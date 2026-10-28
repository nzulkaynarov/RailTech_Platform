"""Расчёт · Склад (контракт: tag `stock`, 0.27.0; D2-2, SPEC-v3 §7.4): остатки и резервы, заказы
поставщикам ЗП, приёмка, отгрузки по проектам; «Запросить цену у поставщика» и резерв строки — в
расчёте (tag `calc`).

BFF не решает (CONVENTIONS.md §2 п. 2): остаток, резерв, переходы статусов заказа, приёмку,
отгрузку и права решает ERP (`/api/v1/stock/*`; коды `supply.manage` и `fulfillment.manage` ERP
выдаёт из раздела `erp.stock`). Здесь — доступ к разделам каталога (чтение — `erp.stock`; действия
— `erp.stock` полный; журнал запросов цены — `erp.calc`), поиск заявки и заказа по бизнес-номеру
(id из номера не разбирается), вырезание цен поставщиков по полям с ограничением и перевод ошибок
ERP.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query, status

from app.api.erp_calc import ErpCalc, Number
from app.clients.erp_company import erp_error
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_erp_calc import CalcSheet, to_sheet
from app.schemas_erp_stock import (
    PriceRequest,
    PriceRequestAnswerIn,
    PriceRequestIn,
    PriceRequestList,
    StockAdjustIn,
    StockBalanceList,
    StockProduct,
    StockReceipts,
    StockReservation,
    StockReservationList,
    StockReserveIn,
    StockShipIn,
    StockShipment,
    StockShipmentList,
    StockSupplierList,
    SupplierOrderCancelIn,
    SupplierOrderConfirmIn,
    SupplierOrderCreate,
    SupplierOrderDetail,
    SupplierOrderFromRequest,
    SupplierOrderLineIn,
    SupplierOrderList,
    SupplierOrderPatch,
    SupplierOrderReceiptIn,
    SupplierOrderSendIn,
    prices_visible,
    to_balances,
    to_order,
    to_order_list,
    to_price_request,
    to_product,
    to_receipts,
    to_reservation,
    to_shipment,
    to_shipments,
    to_suppliers,
)

router = APIRouter(prefix="/erp", tags=["stock"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Actor = Annotated[Authed, Depends(require("erp.stock", "full"))]
CalcReader = Annotated[Authed, Depends(require("erp.calc", "read"))]
LineId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=12)]
ProductId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=12)]
ReservationId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=12)]
RequestId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=12)]
OrderNumber = Annotated[str, Path(min_length=1, max_length=40)]

# Отказ ERP (409) -> сообщение для человека; подкод — в `details.reason`.
_CONFLICTS = {
    "NOT_ENOUGH_STOCK": "Столько свободного товара на складе нет.",
    "BELOW_RESERVED": "Остаток не может стать меньше резервов проектов.",
    "BELOW_SHIPPED": "Резерв не может быть меньше уже отгруженного.",
    "TRANSITION_NOT_ALLOWED": "Заказ уже в другом статусе: обновите экран.",
    "ORDER_NOT_DRAFT": "Состав и поставщика можно менять только в черновике.",
    "ORDER_CLOSED": "Заказ закрыт: изменить его нельзя.",
    "ORDER_NOT_CONFIRMED": "Принять товар можно по подтверждённому заказу.",
    "ORDER_HAS_RECEIPTS": "По заказу уже есть приёмка: отменить его нельзя.",
    "EXPECTED_DATE_REQUIRED": "Укажите ожидаемую дату поставки.",
    "SUPPLIER_EMAIL_REQUIRED": "У поставщика нет почты: укажите адрес для письма.",
    "EMAIL_FAILED": "Письмо поставщику не ушло. Статус заказа не изменён: повторите позже.",
    "FULFILLMENT_NOT_READY": "Проект ещё не подписан: отгрузка возможна после подписания договора.",
    "PRODUCT_REQUIRED": "Сначала сопоставьте строку с карточкой каталога.",
    "NO_SHORTAGE": "Дефицита нет: всё удержано резервом или уже заказано.",
    "DEAL_CLOSED": "Заявка закрыта: резерв не берётся.",
    "LINE_NOT_ACTUAL": "Строка принадлежит прежней версии КП.",
    "LINE_NOT_GOODS": "Услугу у поставщика товаров не запрашивают.",
    "RESERVATION_NOT_ACTIVE": "Резерв уже снят или отгружен.",
    "ALREADY_ANSWERED": "Ответ поставщика уже отмечен.",
    "REQUEST_NOT_SENT": "Письмо не ушло: ответ отмечать нечего.",
    "SERVICE_NOT_STOCKED": "Услуги на склад не принимаются.",
    "CALC_NOT_STARTED": "Расчёт ещё не начат.",
}
_FIELDS = {"PRICES_FORBIDDEN": "unit_price", "BAD_CURRENCY": "currency"}


def stock_error(response: Any) -> PlatformError:
    """Ответ ERP -> ошибка контракта: 400 — 422 с полями, 409 — `CONFLICT` с
    `details.reason`, 403 и 404 — с `details.reason` (код ERP в нижнем регистре)."""
    try:
        body = response.json()
    except ValueError:
        body = None
    code = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(code, str):
        return erp_error(response)
    details: dict[str, Any] = {
        "backend_status": response.status_code,
        "backend_code": code,
        "reason": code.lower(),
    }
    for key in ("free", "max", "reserved", "shipped"):
        if isinstance(body.get(key), int):
            details[key] = body[key]
    if response.status_code == 400:
        fields = sorted(body["fields"]) if isinstance(body.get("fields"), dict) else []
        if code in _FIELDS:
            fields = [_FIELDS[code]]
        if fields:
            details["fields"] = fields
        return PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            source="erp",
            details=details,
        )
    if response.status_code == 409:
        message = _CONFLICTS.get(code, "Действие сейчас недоступно: обновите экран.")
        return PlatformError("CONFLICT", message, status_code=409, source="erp", details=details)
    if response.status_code in (403, 404):
        error = erp_error(response)
        error.body.details = {**(error.body.details or {}), "reason": code.lower()}
        if code in _FIELDS:
            error.body.details["fields"] = [_FIELDS[code]]
        return error
    return erp_error(response)


class ErpStock(ErpCalc):
    """Вызовы `/api/v1/stock/*` от имени сотрудника; заявка и заказ ищутся по бизнес-номеру."""

    async def stock(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        response = await self._call(
            "erp", method, f"/api/v1/stock/{path}", json=json, params=params
        )
        if response.status_code >= 400:
            raise stock_error(response)
        return response.json()

    async def order_id(self, number: str) -> int:
        """Заказ поставщику по номеру ЗП: точный отбор `?number=`; `id` из номера не разбирается."""
        data = await self.stock("GET", "orders/", params={"number": number})
        for row in data.get("results", []) if isinstance(data, dict) else []:
            if isinstance(row, dict) and row.get("number") == number:
                return int(row["id"])
        raise PlatformError(
            "NOT_FOUND",
            "Заказа с таким номером нет.",
            status_code=404,
            source="erp",
            details={"reason": "order_not_found"},
        )


def _erp(authed: Authed) -> ErpStock:
    return ErpStock(authed.call)


def _prices(authed: Authed) -> bool:
    return prices_visible(authed.fields, authed.access)


async def _order_lines(erp: ErpStock, lines: list[SupplierOrderLineIn]) -> list[dict[str, Any]]:
    """Строки заказа для ERP: номер заявки -> id сделки (один поиск на номер), `line_id` — строка
    расчёта этой заявки. `request` и `line_id` — только вместе; оба `null` отвязывают строку от
    проекта, без обоих ключей привязка не меняется."""
    deals: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for line in lines:
        row = line.model_dump(exclude_unset=True)
        row["product_id"] = int(row["product_id"])
        if "id" in row:
            row["id"] = int(row["id"])
        request = row.pop("request", None)
        line_id = row.pop("line_id", None)
        if "request" in line.model_fields_set or "line_id" in line.model_fields_set:
            if (request is None) != (line_id is None):
                raise PlatformError(
                    "VALIDATION_FAILED",
                    "Проверьте заполнение полей.",
                    status_code=422,
                    details={
                        "fields": ["line_id" if request is not None else "request"],
                        "reason": "request_and_line_together",
                    },
                )
            if request is None:
                row["deal_id"] = None
                row["quote_item_id"] = None
            else:
                if request not in deals:
                    deals[request] = await erp.deal_id(request)
                row["deal_id"] = deals[request]
                row["quote_item_id"] = int(line_id)
        rows.append(row)
    return rows


# --- остатки и резервы -------------------------------------------------------------------------


@router.get("/stock/balances", response_model=StockBalanceList, operation_id="listStockBalances")
async def list_balances(
    authed: Reader,
    q: Annotated[str | None, Query(max_length=200)] = None,
    only: Annotated[str | None, Query(pattern=r"^(reserved|incoming)$")] = None,
) -> StockBalanceList:
    params = {k: v for k, v in (("q", q), ("only", only)) if v}
    return to_balances(await _erp(authed).stock("GET", "balances/", params=params or None))


@router.get(
    "/stock/balances/{product_id}", response_model=StockProduct, operation_id="getStockProduct"
)
async def get_product(authed: Reader, product_id: ProductId) -> StockProduct:
    return to_product(await _erp(authed).stock("GET", f"balances/{int(product_id)}/"))


@router.post("/stock/adjustments", response_model=StockProduct, operation_id="adjustStock")
async def adjust(authed: Actor, body: StockAdjustIn) -> StockProduct:
    payload = body.model_dump(exclude_none=True)
    payload["product_id"] = int(payload["product_id"])
    return to_product(await _erp(authed).stock("POST", "adjustments/", json=payload))


@router.get(
    "/stock/reservations",
    response_model=StockReservationList,
    operation_id="listStockReservations",
)
async def list_reservations(
    authed: Reader,
    request: Annotated[str | None, Query(max_length=40)] = None,
    product_id: Annotated[str | None, Query(pattern=r"^[0-9]+$", max_length=12)] = None,
) -> StockReservationList:
    erp = _erp(authed)
    params: dict[str, Any] = {}
    if request:
        params["deal_id"] = await erp.deal_id(request)
    if product_id:
        params["product_id"] = int(product_id)
    data = await erp.stock("GET", "reservations/", params=params or None)
    return StockReservationList(items=[to_reservation(r) for r in data.get("results", [])])


@router.delete(
    "/stock/reservations/{reservation_id}",
    response_model=StockReservation,
    operation_id="releaseStockReservation",
)
async def release_reservation(authed: Actor, reservation_id: ReservationId) -> StockReservation:
    return to_reservation(
        await _erp(authed).stock("DELETE", f"reservations/{int(reservation_id)}/")
    )


# --- резерв строки и запрос цены в расчёте -----------------------------------------------------


async def _sheet(erp: ErpStock, authed: Authed, deal_id: int) -> CalcSheet:
    raw = await erp.call_calc("GET", f"{deal_id}/")
    return to_sheet(raw, authed.fields, authed.access)


@router.put(
    "/calc/{number}/lines/{line_id}/reserve",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="reserveCalcLine",
    tags=["calc"],
)
async def reserve_line(
    authed: Actor, number: Number, line_id: LineId, body: StockReserveIn
) -> CalcSheet:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    await erp.stock(
        "POST",
        "reservations/",
        json={"deal_id": deal_id, "quote_item_id": int(line_id), "quantity": body.quantity},
    )
    return await _sheet(erp, authed, deal_id)


@router.delete(
    "/calc/{number}/lines/{line_id}/reserve",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="releaseCalcLineReservation",
    tags=["calc"],
)
async def release_line(authed: Actor, number: Number, line_id: LineId) -> CalcSheet:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    held = await erp.stock("GET", "reservations/", params={"deal_id": deal_id})
    found = next(
        (r for r in held.get("results", []) if str(r.get("quote_item_id")) == line_id), None
    )
    if found is None:
        raise PlatformError(
            "NOT_FOUND",
            "Резерва у этой строки нет.",
            status_code=404,
            source="erp",
            details={"reason": "reservation_not_found"},
        )
    await erp.stock("DELETE", f"reservations/{int(found['id'])}/")
    return await _sheet(erp, authed, deal_id)


@router.get(
    "/calc/{number}/price-requests",
    response_model=PriceRequestList,
    operation_id="listCalcPriceRequests",
    tags=["calc"],
)
async def list_price_requests(authed: CalcReader, number: Number) -> PriceRequestList:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    data = await erp.stock("GET", "price-requests/", params={"deal_id": deal_id})
    return PriceRequestList(items=[to_price_request(r) for r in data.get("results", [])])


@router.post(
    "/calc/{number}/price-requests",
    response_model=PriceRequest,
    operation_id="createCalcPriceRequest",
    tags=["calc"],
)
async def create_price_request(authed: Actor, number: Number, body: PriceRequestIn) -> PriceRequest:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    payload: dict[str, Any] = {
        "deal_id": deal_id,
        "supplier_id": int(body.supplier_id),
        "line_ids": [int(i) for i in body.line_ids],
    }
    if body.note:
        payload["note"] = body.note
    if body.to_email:
        payload["to_email"] = str(body.to_email)
    return to_price_request(await erp.stock("POST", "price-requests/", json=payload))


@router.post(
    "/price-requests/{request_id}/answer",
    response_model=PriceRequest,
    operation_id="answerPriceRequest",
    tags=["calc"],
)
async def answer_price_request(
    authed: Actor,
    request_id: RequestId,
    body: Annotated[PriceRequestAnswerIn | None, Body()] = None,
) -> PriceRequest:
    note = body.note if body is not None and body.note else ""
    return to_price_request(
        await _erp(authed).stock(
            "POST", f"price-requests/{int(request_id)}/answer/", json={"note": note}
        )
    )


# --- поставщики и заказы -----------------------------------------------------------------------


@router.get("/stock/suppliers", response_model=StockSupplierList, operation_id="listStockSuppliers")
async def list_suppliers(
    authed: Reader, q: Annotated[str | None, Query(max_length=100)] = None
) -> StockSupplierList:
    return to_suppliers(
        await _erp(authed).stock("GET", "suppliers/", params={"q": q} if q else None)
    )


@router.get("/stock/orders", response_model=SupplierOrderList, operation_id="listSupplierOrders")
async def list_orders(
    authed: Reader,
    status_: Annotated[
        str | None, Query(alias="status", pattern=r"^(draft|sent|confirmed|received|cancelled)$")
    ] = None,
    supplier_id: Annotated[str | None, Query(pattern=r"^[0-9]+$", max_length=12)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    overdue: Annotated[bool, Query()] = False,
) -> SupplierOrderList:
    params: dict[str, Any] = {}
    if status_:
        params["status"] = status_
    if supplier_id:
        params["supplier_id"] = int(supplier_id)
    if q:
        params["q"] = q
    if overdue:
        params["overdue"] = 1
    data = await _erp(authed).stock("GET", "orders/", params=params or None)
    return to_order_list(data, _prices(authed))


@router.get(
    "/stock/overdue", response_model=SupplierOrderList, operation_id="listOverdueSupplierOrders"
)
async def list_overdue(authed: Actor) -> SupplierOrderList:
    data = await _erp(authed).stock("GET", "orders/", params={"overdue": 1})
    return to_order_list(data, _prices(authed))


@router.post(
    "/stock/orders",
    response_model=SupplierOrderDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSupplierOrder",
)
async def create_order(authed: Actor, body: SupplierOrderCreate) -> SupplierOrderDetail:
    erp = _erp(authed)
    payload: dict[str, Any] = {
        "supplier_id": int(body.supplier_id),
        "lines": await _order_lines(erp, body.lines),
    }
    if body.expected_date is not None:
        payload["expected_date"] = body.expected_date.isoformat()
    if body.note is not None:
        payload["note"] = body.note
    if body.currency:
        payload["currency"] = body.currency
    return to_order(await erp.stock("POST", "orders/", json=payload), _prices(authed))


@router.post(
    "/stock/orders/from-request",
    response_model=SupplierOrderDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSupplierOrderFromRequest",
)
async def create_order_from_request(
    authed: Actor, body: SupplierOrderFromRequest
) -> SupplierOrderDetail:
    erp = _erp(authed)
    deal_id = await erp.deal_id(body.request)
    data = await erp.stock(
        "POST", "orders/from-deal/", json={"deal_id": deal_id, "supplier_id": int(body.supplier_id)}
    )
    return to_order(data, _prices(authed))


@router.get(
    "/stock/orders/{order_number}",
    response_model=SupplierOrderDetail,
    operation_id="getSupplierOrder",
)
async def get_order(authed: Reader, order_number: OrderNumber) -> SupplierOrderDetail:
    erp = _erp(authed)
    order_id = await erp.order_id(order_number)
    return to_order(await erp.stock("GET", f"orders/{order_id}/"), _prices(authed))


@router.patch(
    "/stock/orders/{order_number}",
    response_model=SupplierOrderDetail,
    operation_id="updateSupplierOrder",
)
async def update_order(
    authed: Actor, order_number: OrderNumber, body: SupplierOrderPatch
) -> SupplierOrderDetail:
    patch = body.model_dump(exclude_unset=True, exclude={"lines", "expected_date"})
    erp = _erp(authed)
    if "supplier_id" in patch:
        patch["supplier_id"] = int(patch["supplier_id"])
    if "expected_date" in body.model_fields_set:
        patch["expected_date"] = body.expected_date.isoformat() if body.expected_date else None
    if not patch and body.lines is None:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            details={"reason": "nothing_to_change"},
        )
    if body.lines is not None:
        patch["lines"] = await _order_lines(erp, body.lines)
    order_id = await erp.order_id(order_number)
    return to_order(await erp.stock("PATCH", f"orders/{order_id}/", json=patch), _prices(authed))


async def _transition(
    authed: Authed, order_number: str, action: str, payload: dict[str, Any]
) -> SupplierOrderDetail:
    erp = _erp(authed)
    order_id = await erp.order_id(order_number)
    data = await erp.stock("POST", f"orders/{order_id}/{action}/", json=payload)
    return to_order(data, _prices(authed))


@router.post(
    "/stock/orders/{order_number}/send",
    response_model=SupplierOrderDetail,
    operation_id="sendSupplierOrder",
)
async def send_order(
    authed: Actor,
    order_number: OrderNumber,
    body: Annotated[SupplierOrderSendIn | None, Body()] = None,
) -> SupplierOrderDetail:
    email = str(body.to_email) if body is not None and body.to_email else ""
    return await _transition(authed, order_number, "send", {"to_email": email})


@router.post(
    "/stock/orders/{order_number}/confirm",
    response_model=SupplierOrderDetail,
    operation_id="confirmSupplierOrder",
)
async def confirm_order(
    authed: Actor,
    order_number: OrderNumber,
    body: Annotated[SupplierOrderConfirmIn | None, Body()] = None,
) -> SupplierOrderDetail:
    payload: dict[str, Any] = {}
    if body is not None and body.expected_date is not None:
        payload["expected_date"] = body.expected_date.isoformat()
    return await _transition(authed, order_number, "confirm", payload)


@router.post(
    "/stock/orders/{order_number}/cancel",
    response_model=SupplierOrderDetail,
    operation_id="cancelSupplierOrder",
)
async def cancel_order(
    authed: Actor,
    order_number: OrderNumber,
    body: Annotated[SupplierOrderCancelIn | None, Body()] = None,
) -> SupplierOrderDetail:
    return await _transition(
        authed,
        order_number,
        "cancel",
        {"reason": body.reason if body is not None and body.reason else ""},
    )


@router.post(
    "/stock/orders/{order_number}/receipts",
    response_model=SupplierOrderDetail,
    operation_id="receiveSupplierOrder",
)
async def receive_order(
    authed: Actor, order_number: OrderNumber, body: SupplierOrderReceiptIn
) -> SupplierOrderDetail:
    payload: dict[str, Any] = {
        "lines": [
            {
                "order_line_id": int(line.order_line_id),
                "quantity": line.quantity,
                "cell": line.cell or "",
            }
            for line in body.lines
        ],
    }
    if body.supplier_doc:
        payload["supplier_doc"] = body.supplier_doc
    if body.note:
        payload["note"] = body.note
    return await _transition(authed, order_number, "receipts", payload)


# --- приёмка и отгрузки ------------------------------------------------------------------------


@router.get("/stock/receipts", response_model=StockReceipts, operation_id="listStockReceipts")
async def list_receipts(authed: Reader) -> StockReceipts:
    return to_receipts(await _erp(authed).stock("GET", "receipts/"))


@router.get("/stock/shipments", response_model=StockShipmentList, operation_id="listStockShipments")
async def list_shipments(
    authed: Reader, request: Annotated[str | None, Query(max_length=40)] = None
) -> StockShipmentList:
    erp = _erp(authed)
    params = {"deal_id": await erp.deal_id(request)} if request else None
    return to_shipments(await erp.stock("GET", "shipments/", params=params))


@router.post(
    "/stock/shipments",
    response_model=StockShipment,
    status_code=status.HTTP_201_CREATED,
    operation_id="shipFromStock",
)
async def ship(authed: Actor, body: StockShipIn) -> StockShipment:
    erp = _erp(authed)
    payload: dict[str, Any] = {
        "deal_id": await erp.deal_id(body.request),
        "lines": [
            {"reservation_id": int(line.reservation_id), "quantity": line.quantity}
            for line in body.lines
        ],
    }
    for key in ("tracking", "carrier", "note"):
        value = getattr(body, key)
        if value:
            payload[key] = value
    return to_shipment(await erp.stock("POST", "shipments/", json=payload))
