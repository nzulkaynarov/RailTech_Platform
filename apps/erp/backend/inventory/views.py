"""Склад для Платформы (D2-2, SPEC-v3 §7.4 «Склад»): `/api/v1/stock/*` — остатки, резервы, корректировки, отгрузки.

Тонкие обёртки (CONVENTIONS.md §5, Rule 8): проверить тело → вызвать одну функцию сервиса → вернуть. Право мутации
объявлено на вьюхе (`RoleGatedViewMixin`: `supply.manage` — резервы, корректировки; `fulfillment.manage` — отгрузки), чтение —
сотрудник компании; отказ сервиса — `{"detail": "<CODE>"}` со статусом из `StockError`.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from inventory.access import StockError, require_staff
from inventory.models import Reservation, Shipment
from inventory.serializers import (
    StockAdjustInSerializer,
    StockBalanceListSerializer,
    StockErrorSerializer,
    StockProductSerializer,
    StockReservationListSerializer,
    StockReservationSerializer,
    StockReserveInSerializer,
    StockShipInSerializer,
    StockShipmentListSerializer,
    StockShipmentSerializer,
    StockSupplierListSerializer,
)
from inventory.services import overview, stock
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin

TAGS = ["Stock"]
ERRORS = {
    400: OpenApiResponse(StockErrorSerializer, description="Тело не прошло проверку"),
    403: OpenApiResponse(StockErrorSerializer, description="Нет права или не сотрудник"),
    404: OpenApiResponse(StockErrorSerializer, description="Объекта нет"),
    409: OpenApiResponse(StockErrorSerializer, description="Состояние не позволяет (мало остатка, резерв, статус)"),
}
READ_ERRORS = {403: ERRORS[403], 404: ERRORS[404]}


def fail(exc: StockError) -> Response:
    return Response({"detail": exc.code, **exc.extra}, status=exc.status)


def invalid(serializer) -> Response:
    return Response({"detail": "VALIDATION_FAILED", "fields": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class StockBalanceListView(APIView):
    """GET /api/v1/stock/balances/ — остатки и резервы по номенклатуре."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stock_balances_list",
        summary="Остатки и резервы по номенклатуре",
        tags=TAGS,
        parameters=[
            OpenApiParameter("q", str, description="Слова названия, артикула, SKU; ищет по всей номенклатуре"),
            OpenApiParameter("only", str, enum=["reserved", "incoming"], description="Только с резервом / с приходом"),
        ],
        responses={200: StockBalanceListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        only = request.query_params.get("only", "")
        try:
            return Response(
                overview.balances(
                    request.user,
                    q=request.query_params.get("q", "")[:200],
                    only=only if only in ("reserved", "incoming") else "",
                )
            )
        except StockError as exc:
            return fail(exc)


class StockProductView(APIView):
    """GET /api/v1/stock/balances/<product_id>/ — товар: ячейки, резервы по проектам, приход, движения."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stock_product_detail",
        summary="Товар на складе",
        tags=TAGS,
        responses={200: StockProductSerializer, **READ_ERRORS},
    )
    def get(self, request, product_id: int):
        try:
            return Response(overview.product_detail(request.user, product_id))
        except StockError as exc:
            return fail(exc)


class StockAdjustView(RoleGatedViewMixin, APIView):
    """POST /api/v1/stock/adjustments/ — оприходовать или списать вручную (начальные остатки, инвентаризация)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_adjust",
        summary="Корректировка остатка: оприходовать или списать",
        tags=TAGS,
        request=StockAdjustInSerializer,
        responses={200: StockProductSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = StockAdjustInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            stock.adjust(request.user, data["product_id"], data["quantity"], cell=data["cell"], note=data["note"])
            return Response(overview.product_detail(request.user, data["product_id"]))
        except StockError as exc:
            return fail(exc)


class StockReservationListView(RoleGatedViewMixin, APIView):
    """GET/POST /api/v1/stock/reservations/ — резервы; POST — зарезервировать (или изменить количество) под строку расчёта."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "supply.manage"}

    @extend_schema(
        operation_id="stock_reservations_list",
        summary="Резервы под проекты",
        tags=TAGS,
        parameters=[
            OpenApiParameter("deal_id", int),
            OpenApiParameter("product_id", int),
            OpenApiParameter(
                "status", str, enum=list(("active", "released", "fulfilled")), description="По умолчанию — действующие"
            ),
        ],
        responses={200: StockReservationListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            rows = overview.reservations(
                request.user,
                deal_id=_int(request.query_params.get("deal_id")),
                product_id=_int(request.query_params.get("product_id")),
                status=request.query_params.get("status", "active"),
            )
            return Response({"results": rows})
        except StockError as exc:
            return fail(exc)

    @extend_schema(
        operation_id="stock_reserve",
        summary="Зарезервировать товар под строку расчёта",
        tags=TAGS,
        request=StockReserveInSerializer,
        responses={201: StockReservationSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = StockReserveInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            reservation = stock.reserve(request.user, data["deal_id"], data["quote_item_id"], data["quantity"])
            reservation = Reservation.objects.select_related("product", "deal__company", "created_by").get(
                pk=reservation.pk
            )
            return Response(overview.present_reservation(reservation), status=status.HTTP_201_CREATED)
        except StockError as exc:
            return fail(exc)


class StockReservationView(RoleGatedViewMixin, APIView):
    """DELETE /api/v1/stock/reservations/<id>/ — снять резерв."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"DELETE": "supply.manage"}

    @extend_schema(
        operation_id="stock_reservation_release",
        summary="Снять резерв",
        tags=TAGS,
        responses={200: StockReservationSerializer, **ERRORS},
    )
    def delete(self, request, reservation_id: int):
        try:
            reservation = stock.release(request.user, reservation_id)
            reservation = Reservation.objects.select_related("product", "deal__company", "created_by").get(
                pk=reservation.pk
            )
            return Response(overview.present_reservation(reservation))
        except StockError as exc:
            return fail(exc)


class StockShipmentListView(RoleGatedViewMixin, APIView):
    """GET/POST /api/v1/stock/shipments/ — отгрузки по проектам; POST — отгрузить со склада по резервам заявки."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "fulfillment.manage"}

    @extend_schema(
        operation_id="stock_shipments_list",
        summary="Отгрузки по проектам",
        tags=TAGS,
        parameters=[OpenApiParameter("deal_id", int)],
        responses={200: StockShipmentListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            return Response(overview.shipments(request.user, deal_id=_int(request.query_params.get("deal_id"))))
        except StockError as exc:
            return fail(exc)

    @extend_schema(
        operation_id="stock_ship",
        summary="Отгрузить со склада по резервам заявки (накладная ОТГ)",
        tags=TAGS,
        request=StockShipInSerializer,
        responses={201: StockShipmentSerializer, **ERRORS},
    )
    def post(self, request):
        serializer = StockShipInSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        try:
            shipment = stock.ship(
                request.user,
                data["deal_id"],
                [stock.ShipInput(line["reservation_id"], line["quantity"]) for line in data["lines"]],
                tracking=data["tracking"],
                carrier=data["carrier"],
                note=data["note"],
            )
            shipment = (
                Shipment.objects.select_related("deal__company", "shipped_by")
                .prefetch_related("lines__product")
                .get(pk=shipment.pk)
            )
            return Response(overview.present_shipment(shipment), status=status.HTTP_201_CREATED)
        except StockError as exc:
            return fail(exc)


class StockSupplierListView(APIView):
    """GET /api/v1/stock/suppliers/?q= — внешние поставщики для выбора (запрос цены, заказ)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stock_suppliers_list",
        summary="Поставщики для выбора",
        tags=TAGS,
        parameters=[OpenApiParameter("q", str, description="Название или ИНН")],
        responses={200: StockSupplierListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            require_staff(request.user)
            return Response({"results": overview.suppliers(request.user, request.query_params.get("q", "")[:100])})
        except StockError as exc:
            return fail(exc)
