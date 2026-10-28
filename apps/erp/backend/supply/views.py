"""Закупки для Платформы (D2-2, SPEC-v3 §7.4 «Склад»): `/api/v1/stock/orders*`, `receipts`, `price-requests*`, `overdue`.

Тонкие обёртки: проверить тело → вызвать одну функцию `supply.services` → вернуть. Право мутации объявлено на вьюхе
(`supply.manage`), чтение — сотрудник компании; цены поставщиков режет сервис (`quote.view_cost_margin` или зона товаров).
Отказ — `{"detail": "<CODE>"}` со статусом из `StockError`.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from inventory.access import StockError
from inventory.serializers import StockErrorSerializer
from inventory.services import overview
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from supply.models import PriceRequest
from supply.serializers import (
    OrderCancelInSerializer,
    OrderConfirmInSerializer,
    OrderCreateInSerializer,
    OrderDetailSerializer,
    OrderFromDealInSerializer,
    OrderListSerializer,
    OrderPatchInSerializer,
    OrderSendInSerializer,
    OverdueListSerializer,
    PriceRequestAnswerInSerializer,
    PriceRequestInSerializer,
    PriceRequestListSerializer,
    PriceRequestSerializer,
    ReceiptInSerializer,
    ReceiptsSerializer,
)
from supply.services import orders, price_requests

from core.permissions import RoleGatedViewMixin

TAGS = ["Stock"]
ERRORS = {
    400: OpenApiResponse(StockErrorSerializer, description="Тело не прошло проверку"),
    403: OpenApiResponse(StockErrorSerializer, description="Нет права, не сотрудник или нет права на цены поставщиков"),
    404: OpenApiResponse(StockErrorSerializer, description="Заказа, строки, поставщика или заявки нет"),
    409: OpenApiResponse(
        StockErrorSerializer,
        description="Состояние не позволяет (недопустимый переход статуса, нет адреса, письмо не ушло — `EMAIL_FAILED`, мало товара)",
    ),
}
READ_ERRORS = {403: ERRORS[403], 404: ERRORS[404]}
ORDER_STATUS_PARAM = OpenApiParameter(
    "status", str, enum=["draft", "sent", "confirmed", "received", "cancelled"], description="Статус заказа"
)


def fail(exc: StockError) -> Response:
    return Response({"detail": exc.code, **exc.extra}, status=exc.status)


def invalid(serializer) -> Response:
    return Response({"detail": "VALIDATION_FAILED", "fields": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _line_inputs(rows) -> list[orders.LineInput]:
    return [
        orders.LineInput(
            id=row.get("id"),
            product_id=row["product_id"],
            name=row.get("name", ""),
            article=row.get("article", ""),
            unit=row.get("unit", ""),
            quantity=row["quantity"],
            unit_price=row.get("unit_price"),
            price_given="unit_price" in row,
            deal_id=row.get("deal_id"),
            quote_item_id=row.get("quote_item_id"),
            link_given="deal_id" in row or "quote_item_id" in row,
        )
        for row in rows
    ]


class OrderListView(RoleGatedViewMixin, APIView):
    """GET/POST /api/v1/stock/orders/ — заказы поставщикам; POST — создать черновик."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_orders_list",
        summary="Заказы поставщикам",
        tags=TAGS,
        parameters=[
            ORDER_STATUS_PARAM,
            OpenApiParameter("supplier_id", int),
            OpenApiParameter("q", str, description="Номер, поставщик, название позиции"),
            OpenApiParameter("number", str, description="Точный номер ЗП-ГГГГ-NNN"),
            OpenApiParameter("overdue", bool, description="Только просроченные"),
        ],
        responses={200: OrderListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        params = request.query_params
        try:
            return Response(
                orders.list_orders(
                    request.user,
                    status=params.get("status", ""),
                    supplier_id=_int(params.get("supplier_id")),
                    q=params.get("q", "")[:200],
                    number=params.get("number", "")[:32],
                    overdue=str(params.get("overdue", "")).lower() in ("1", "true", "yes"),
                )
            )
        except StockError as exc:
            return fail(exc)

    @extend_schema(
        operation_id="stock_order_create",
        summary="Создать заказ поставщику (черновик)",
        tags=TAGS,
        request=OrderCreateInSerializer,
        responses={201: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = OrderCreateInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            order = orders.create_order(
                request.user,
                orders.OrderInput(
                    supplier_id=data["supplier_id"],
                    expected_date=data.get("expected_date"),
                    expected_given=True,
                    note=data.get("note", ""),
                    currency=data.get("currency") or None,
                    lines=_line_inputs(data["lines"]),
                ),
            )
            return Response(orders.present_detail(request.user, order), status=status.HTTP_201_CREATED)
        except StockError as exc:
            return fail(exc)


class OrderFromDealView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/orders/from-deal/ — черновик ЗП на дефицит проекта."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_from_deal",
        summary="Черновик заказа на дефицит проекта",
        tags=TAGS,
        request=OrderFromDealInSerializer,
        responses={201: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = OrderFromDealInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            order = orders.create_from_deal(request.user, data["deal_id"], data["supplier_id"])
            return Response(orders.present_detail(request.user, order), status=status.HTTP_201_CREATED)
        except StockError as exc:
            return fail(exc)


class OrderView(RoleGatedViewMixin, APIView):
    """GET/PATCH /api/v1/stock/orders/<id>/ — карточка заказа; правка (состав — только в черновике)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"PATCH": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_detail",
        summary="Заказ поставщику",
        tags=TAGS,
        responses={200: OrderDetailSerializer, **READ_ERRORS},
    )
    def get(self, request, order_id: int):
        try:
            return Response(orders.get_order(request.user, order_id))
        except StockError as exc:
            return fail(exc)

    @extend_schema(
        operation_id="stock_order_update",
        summary="Изменить заказ (состав — в черновике; ожидаемая дата и примечание — пока заказ не закрыт)",
        tags=TAGS,
        request=OrderPatchInSerializer,
        responses={200: OrderDetailSerializer, **ERRORS},
    )
    def patch(self, request, order_id: int):
        serializer = OrderPatchInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            order = orders.update_order(
                request.user,
                order_id,
                orders.OrderInput(
                    supplier_id=data.get("supplier_id"),
                    expected_date=data.get("expected_date"),
                    expected_given="expected_date" in data,
                    note=data.get("note"),
                    currency=data.get("currency") if "currency" in data else None,
                    lines=_line_inputs(data["lines"]) if "lines" in data else None,
                ),
            )
            return Response(orders.present_detail(request.user, order))
        except StockError as exc:
            return fail(exc)


class OrderSendView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/orders/<id>/send/ — отправить поставщику письмом (черновик → отправлен)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_send",
        summary="Отправить заказ поставщику (письмо)",
        tags=TAGS,
        request=OrderSendInSerializer,
        responses={200: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request, order_id: int):
        serializer = OrderSendInSerializer(data=request.data or {})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            order = orders.send_order(request.user, order_id, to_email=serializer.validated_data["to_email"])
            return Response(orders.present_detail(request.user, order))
        except StockError as exc:
            return fail(exc)


class OrderConfirmView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/orders/<id>/confirm/ — поставщик подтвердил (отправлен → подтверждён); нужна ожидаемая дата."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_confirm",
        summary="Отметить подтверждение поставщика",
        tags=TAGS,
        request=OrderConfirmInSerializer,
        responses={200: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request, order_id: int):
        serializer = OrderConfirmInSerializer(data=request.data or {})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            order = orders.confirm_order(
                request.user, order_id, expected_date=serializer.validated_data.get("expected_date")
            )
            return Response(orders.present_detail(request.user, order))
        except StockError as exc:
            return fail(exc)


class OrderCancelView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/orders/<id>/cancel/ — отменить заказ (если по нему ещё ничего не принято)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_cancel",
        summary="Отменить заказ",
        tags=TAGS,
        request=OrderCancelInSerializer,
        responses={200: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request, order_id: int):
        serializer = OrderCancelInSerializer(data=request.data or {})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            order = orders.cancel_order(request.user, order_id, reason=serializer.validated_data["reason"])
            return Response(orders.present_detail(request.user, order))
        except StockError as exc:
            return fail(exc)


class OrderReceiptView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/orders/<id>/receipts/ — приёмка по строкам заказа (частичная); остаток склада растёт."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_order_receive",
        summary="Принять товар от поставщика по строкам заказа",
        tags=TAGS,
        request=ReceiptInSerializer,
        responses={200: OrderDetailSerializer, **ERRORS},
    )
    def post(self, request, order_id: int):
        serializer = ReceiptInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            order = orders.receive(
                request.user,
                order_id,
                [orders.ReceiptInput(row["order_line_id"], row["quantity"], row["cell"]) for row in data["lines"]],
                supplier_doc=data["supplier_doc"],
                note=data["note"],
            )
            return Response(orders.present_detail(request.user, order))
        except StockError as exc:
            return fail(exc)


class ReceiptListView(APIView):
    """GET /api/v1/stock/receipts/ — «Приёмка»: ждут товара и последние приёмки."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stock_receipts_list",
        summary="Приёмка: ожидаемые строки и последние приёмки",
        tags=TAGS,
        responses={200: ReceiptsSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            return Response(overview.pending_receipts(request.user))
        except StockError as exc:
            return fail(exc)


class OverdueListView(APIView):
    """GET /api/v1/stock/overdue/ — просроченные заказы (источник вида очереди `supplier_overdue`)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stock_overdue_list",
        summary="Просроченные заказы поставщикам",
        tags=TAGS,
        responses={200: OverdueListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            return Response({"results": orders.overdue_orders(request.user)})
        except StockError as exc:
            return fail(exc)


class PriceRequestListView(RoleGatedViewMixin, APIView):
    """GET/POST /api/v1/stock/price-requests/ — журнал запросов цены; POST — запросить цену у поставщика письмом."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_price_requests_list",
        summary="Журнал запросов цены у поставщиков",
        tags=TAGS,
        parameters=[OpenApiParameter("deal_id", int), OpenApiParameter("supplier_id", int)],
        responses={200: PriceRequestListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            return Response(
                {
                    "results": price_requests.list_requests(
                        request.user,
                        deal_id=_int(request.query_params.get("deal_id")),
                        supplier_id=_int(request.query_params.get("supplier_id")),
                    )
                }
            )
        except StockError as exc:
            return fail(exc)

    @extend_schema(
        operation_id="stock_price_request_create",
        summary="Запросить цену у поставщика (письмо) по строкам расчёта",
        tags=TAGS,
        request=PriceRequestInSerializer,
        responses={201: PriceRequestSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = PriceRequestInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            created = price_requests.create(
                request.user,
                data["deal_id"],
                data["supplier_id"],
                data["line_ids"],
                note=data["note"],
                to_email=data["to_email"],
            )
            created = PriceRequest.objects.select_related("supplier", "deal", "requested_by", "answered_by").get(
                pk=created.pk
            )
            return Response(price_requests.present(created), status=status.HTTP_201_CREATED)
        except StockError as exc:
            return fail(exc)


class PriceRequestAnswerView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/price-requests/<id>/answer/ — отметить, что поставщик ответил (цена внесена в расчёт)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_price_request_answer",
        summary="Отметить ответ поставщика",
        tags=TAGS,
        request=PriceRequestAnswerInSerializer,
        responses={200: PriceRequestSerializer, **ERRORS},
    )
    def post(self, request, request_id: int):
        serializer = PriceRequestAnswerInSerializer(data=request.data or {})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            answered = price_requests.mark_answered(request.user, request_id, serializer.validated_data["note"])
            answered = PriceRequest.objects.select_related("supplier", "deal", "requested_by", "answered_by").get(
                pk=answered.pk
            )
            return Response(price_requests.present(answered))
        except StockError as exc:
            return fail(exc)
