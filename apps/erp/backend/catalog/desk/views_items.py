"""Позиции номенклатуры и поставщики (D2-3): `/api/v1/catalog/items/` и `/api/v1/catalog/suppliers/`."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from parties.models import Company
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from catalog.desk import items, suppliers
from catalog.desk.serializers import (
    DeskItemDetail,
    DeskItemIn,
    DeskItemRow,
    DeskOffer,
    DeskOfferIn,
    DeskSupplierDetail,
    DeskSupplierRow,
)
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, PAGE, PAGE_SIZE, REFUSED, SEARCH, DeskViewSet, refuse
from catalog.models import Product, SupplierOffer

_KIND = OpenApiParameter("kind", str, enum=list(items.ALL_KINDS), description="Тип позиции.")
_CATEGORY = OpenApiParameter("category", int, description="Id категории.")


class ItemDeskViewSet(DeskViewSet):
    """Позиции: поиск и фильтр (чтение — любой сотрудник), создание и правка — `catalog.manage`."""

    required_permissions = {"create": "catalog.manage", "partial_update": "catalog.manage"}
    lookup_value_regex = r"\d+"
    queryset = Product.objects.none()
    serializer_class = DeskItemDetail

    def _product(self, pk) -> Product:
        product = (
            Product.objects.exclude(status__code="ARCHIVED")
            .select_related("domain_type", "uom", "category", "status", "brand")
            .filter(pk=pk)
            .first()
        )
        if product is None:
            raise NotFound()
        return product

    @extend_schema(
        operation_id="catalog_items_list",
        summary="Catalog items for the nomenclature screen",
        description=(
            "Позиции номенклатуры с типом, единицей, НДС и числом предложений. Цены поставщиков здесь нет вовсе — они в "
            "карточке и только с правом на `supplier_prices`."
        ),
        parameters=[SEARCH, _KIND, _CATEGORY, PAGE, PAGE_SIZE],
        responses={200: DeskItemRow},
        tags=["Catalog"],
    )
    def list(self, request):
        queryset = items.list_queryset(request.query_params)
        vat_default = items.company_vat_default()
        return self.page_of(queryset, lambda rows: [items.item_row(p, vat_default) for p in rows])

    @extend_schema(
        operation_id="catalog_items_retrieve",
        summary="Catalog item card with supplier offers",
        description="Предложения поставщиков: цена закупки (`price`) — `null` без права на цены поставщиков.",
        responses={200: DeskItemDetail, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def retrieve(self, request, pk=None):
        return Response(items.item_detail(self._product(pk), request.user))

    @extend_schema(
        operation_id="catalog_items_create",
        summary="Create a catalog item",
        description="Needs `catalog.manage`. Новая позиция — черновик; тип задаёт домен и политику исполнения.",
        request=DeskItemIn,
        responses={201: DeskItemDetail, 400: REFUSED, 403: FORBIDDEN},
        tags=["Catalog"],
    )
    def create(self, request):
        body = DeskItemIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                product = items.create_item(dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(self._product(product.pk), request.user), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="catalog_items_update",
        summary="Edit a catalog item",
        description="Needs `catalog.manage`. НДС: пусто — ставка компании по умолчанию.",
        request=DeskItemIn,
        responses={200: DeskItemDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def partial_update(self, request, pk=None):
        product = self._product(pk)
        body = DeskItemIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                items.update_item(product, dict(body.validated_data))
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(self._product(product.pk), request.user))


class SupplierDeskViewSet(DeskViewSet):
    """Поставщики с предложениями; правка условий предложения — `supply.manage`, цены — ещё и право на цены поставщиков."""

    required_permissions = {"partial_update_offer": "supply.manage"}
    lookup_value_regex = r"\d+"
    queryset = Company.objects.none()
    serializer_class = DeskSupplierDetail

    def _supplier(self, pk) -> Company:
        company = suppliers.supplier_queryset({}).filter(pk=pk).first() if str(pk).isdigit() else None
        if company is None:
            raise NotFound()
        return company

    @extend_schema(
        operation_id="catalog_suppliers_list",
        summary="Suppliers with offers summary",
        description="Поставщики: число предложений, истёкшие и истекающие сроки цен. Цен нет.",
        parameters=[SEARCH, PAGE, PAGE_SIZE],
        responses={200: DeskSupplierRow},
        tags=["Catalog"],
    )
    def list(self, request):
        return self.page_of(
            suppliers.supplier_queryset(request.query_params), lambda rows: [suppliers.supplier_row(c) for c in rows]
        )

    @extend_schema(
        operation_id="catalog_suppliers_retrieve",
        summary="Supplier card with offers",
        description="Предложения поставщика: квота, сроки поставки и действия цены; `price` — `null` без права на цены поставщиков.",
        responses={200: DeskSupplierDetail, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def retrieve(self, request, pk=None):
        return Response(suppliers.supplier_detail(self._supplier(pk), request.user))

    @extend_schema(
        operation_id="catalog_suppliers_offer_update",
        summary="Edit a supplier offer",
        description=(
            "Needs `supply.manage`. Квота, минимальный заказ, сроки поставки, окно действия цены, признак «действует». "
            "Цена (`price`) — только с правом на цены поставщиков: иначе 403 `SUPPLIER_PRICES_REQUIRED`."
        ),
        request=DeskOfferIn,
        responses={200: DeskOffer, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["patch"], url_path=r"offers/(?P<offer_id>[0-9]+)", url_name="offer")
    def partial_update_offer(self, request, pk=None, offer_id=None):
        offer = (
            SupplierOffer.objects.select_related("supplier", "product", "currency", "stock_status")
            .filter(pk=offer_id, supplier_id=pk)
            .first()
        )
        if offer is None:
            raise NotFound()
        body = DeskOfferIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                suppliers.update_offer(offer, dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        offer.refresh_from_db()
        from catalog.desk.access import can_view_supplier_prices

        return Response(items.offer_row(offer, show_price=can_view_supplier_prices(request.user)))
