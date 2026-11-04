"""Позиции номенклатуры и поставщики (D2-3): `/api/v1/catalog/items/` и `/api/v1/catalog/suppliers/`."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from parties.models import Company
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from catalog.desk import images, items, proposals, suppliers
from catalog.desk.serializers import (
    DeskImage,
    DeskImageIn,
    DeskImageUpload,
    DeskItemDetail,
    DeskItemIn,
    DeskItemRow,
    DeskOffer,
    DeskOfferCreateIn,
    DeskOfferHistoryRow,
    DeskOfferIn,
    DeskReturnIn,
    DeskSupplierDetail,
    DeskSupplierIn,
    DeskSupplierRow,
)
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, PAGE, PAGE_SIZE, REFUSED, SEARCH, DeskViewSet, refuse
from catalog.models import Product, ProductFieldProposal, SupplierOffer

_KIND = OpenApiParameter("kind", str, enum=list(items.ALL_KINDS), description="Тип позиции.")
_CATEGORY = OpenApiParameter("category", int, description="Id категории.")
_REVIEW = OpenApiParameter(
    "review",
    str,
    enum=["waiting"],
    description=(
        "Очередь проверки партнёров (PART-3): карточки на проверке и с открытыми предложениями партнёров, старые сверху; "
        "в строке — `review` (срок) и `completeness`."
    ),
)
_PROPOSALS = OpenApiParameter(
    "proposals", str, enum=["pending"], description="Только позиции с изменениями от поставщиков на одобрении."
)


class ItemDeskViewSet(DeskViewSet):
    """Позиции: поиск и фильтр (чтение — любой сотрудник), создание и правка — `catalog.manage`."""

    required_permissions = {
        "create": "catalog.manage",
        "partial_update": "catalog.manage",
        "publish": "catalog.publish",
        "unpublish": "catalog.publish",
        "return_to_partner": "catalog.publish",
        "add_image": "catalog.manage",
        "image": "catalog.manage",
    }
    lookup_value_regex = r"\d+"
    queryset = Product.objects.none()
    serializer_class = DeskItemDetail

    def _product(self, pk) -> Product:
        product = (
            Product.objects.exclude(status__code="ARCHIVED")
            .select_related(
                "domain_type",
                "uom",
                "category",
                "status",
                "brand",
                "brand__country",
                "source_supplier",
                "country_of_origin",
            )
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
        parameters=[SEARCH, _KIND, _CATEGORY, _PROPOSALS, _REVIEW, PAGE, PAGE_SIZE],
        responses={200: DeskItemRow},
        tags=["Catalog"],
    )
    def list(self, request):
        queryset = items.list_queryset(request.query_params)
        vat_default = items.company_vat_default()
        waiting = request.query_params.get("review") == "waiting"

        def build(rows):
            extra = items.queue_rows(rows) if waiting else {}
            return [{**items.item_row(p, vat_default), **extra.get(p.pk, {})} for p in rows]

        return self.page_of(queryset, build)

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
                items.update_item(product, dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(self._product(product.pk), request.user))

    @extend_schema(
        operation_id="catalog_items_images_create",
        summary="Upload a product photo",
        description=(
            "Needs `catalog.manage`. JPEG, PNG или WebP до 5 МБ, до 10 фото на товар; первое фото становится главным. "
            "Коды: FILE_TOO_LARGE, FILE_TYPE_NOT_ALLOWED, FILE_CONTENT_MISMATCH, IMAGE_LIMIT_REACHED, NO_FILE_PROVIDED."
        ),
        request={"multipart/form-data": DeskImageUpload},
        responses={201: DeskImage, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="images",
        url_name="images",
        parser_classes=[MultiPartParser, FormParser],
    )
    def add_image(self, request, pk=None):
        product = self._product(pk)
        file = request.FILES.get("image")
        if file is None:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)
        make_main = str(request.data.get("is_main", "")).strip().lower() in ("1", "true", "yes", "on")
        try:
            with transaction.atomic():
                created = images.add_image(product, file, alt=request.data.get("alt_text", ""), make_main=make_main)
        except items.ItemError as error:
            return refuse(error)
        return Response(images.image_row(created), status=status.HTTP_201_CREATED)

    @extend_schema(
        methods=["PATCH"],
        operation_id="catalog_items_images_update",
        summary="Edit a product photo",
        description=(
            "Needs `catalog.manage`. `is_main: true` — главное фото; `sort_order` — новая позиция с нуля (остальные "
            "сдвигаются); `alt_text`. Главное можно только назначить другому, снять нельзя (IMAGE_MAIN_REQUIRED)."
        ),
        request=DeskImageIn,
        responses={200: DeskImage, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="catalog_items_images_destroy",
        summary="Delete a product photo",
        description="Needs `catalog.manage`. Файл удаляется; если было главное, главным становится следующее по порядку.",
        responses={204: None, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"images/(?P<image_id>[0-9]+)",
        url_name="image",
        parser_classes=[JSONParser],
    )
    def image(self, request, pk=None, image_id=None):
        product = self._product(pk)
        try:
            with transaction.atomic():
                if request.method == "DELETE":
                    images.delete_image(product, image_id)
                    return Response(status=status.HTTP_204_NO_CONTENT)
                body = DeskImageIn(data=request.data, partial=True)
                body.is_valid(raise_exception=True)
                changed = images.update_image(product, image_id, dict(body.validated_data))
        except items.ItemError as error:
            if error.code == "IMAGE_NOT_FOUND":
                raise NotFound() from None
            return refuse(error)
        return Response(images.image_row(changed))

    def _set_published(self, request, pk, publish: bool):
        product = self._product(pk)
        try:
            items.set_published(product, publish, request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(self._product(product.pk), request.user))

    @extend_schema(
        operation_id="catalog_items_publish",
        summary="Publish a catalog item",
        description=(
            "Needs `catalog.publish`. Порог полноты (`catalog/publishing.py`): не хватает полей — 409 "
            "`PRODUCT_INCOMPLETE`, список — в `publish.missing` карточки."
        ),
        request=None,
        responses={200: DeskItemDetail, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, pk=None):
        return self._set_published(request, pk, True)

    @extend_schema(
        operation_id="catalog_items_unpublish",
        summary="Unpublish a catalog item",
        description="Needs `catalog.publish`. Опубликованная карточка снова становится черновиком.",
        request=None,
        responses={200: DeskItemDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="unpublish")
    def unpublish(self, request, pk=None):
        return self._set_published(request, pk, False)

    @extend_schema(
        operation_id="catalog_items_return",
        summary="Return a partner card with reasons",
        description=(
            "Needs `catalog.publish`. Карточка партнёра «на проверке» → «возвращена»: общий комментарий и замечания по полям "
            "(`issues`: поле из перечня карточки и текст). Нужна хотя бы одна причина — 400 `REVIEW_REASON_REQUIRED`; поле не из "
            "перечня или длинный текст — 400 `REVIEW_ISSUES_INVALID`. Карточка не на проверке (уже решена) — 409 "
            "`PRODUCT_NOT_ON_REVIEW`. Проверка закрывается решением «возвращена», партнёру уходит письмо."
        ),
        request=DeskReturnIn,
        responses={200: DeskItemDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="return", url_name="return")
    def return_to_partner(self, request, pk=None):
        product = self._product(pk)
        body = DeskReturnIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            items.return_item(product.pk, dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(self._product(product.pk), request.user))


class ProposalDeskViewSet(DeskViewSet):
    """Изменения карточки от поставщиков (CAT-1): принять или отклонить — `catalog.manage`; ответ — карточка позиции."""

    required_permissions = {"accept": "catalog.manage", "reject": "catalog.manage"}
    lookup_value_regex = r"\d+"
    queryset = ProductFieldProposal.objects.none()
    serializer_class = DeskItemDetail

    def _decide(self, request, pk, accept: bool):
        proposal = (
            ProductFieldProposal.objects.select_related("product", "supplier").filter(pk=pk).first()
            if str(pk).isdigit()
            else None
        )
        if proposal is None:
            raise NotFound()
        try:
            with transaction.atomic():
                proposals.decide(proposal, accept, request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(items.item_detail(ItemDeskViewSet()._product(proposal.product_id), request.user))

    @extend_schema(
        operation_id="catalog_field_proposals_accept",
        summary="Accept a supplier change to a catalog item",
        description="Needs `catalog.manage`. Значение из прайса записывается в карточку; уже решённое — 409.",
        request=None,
        responses={200: DeskItemDetail, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        return self._decide(request, pk, True)

    @extend_schema(
        operation_id="catalog_field_proposals_reject",
        summary="Reject a supplier change to a catalog item",
        description="Needs `catalog.manage`. Карточка не меняется; это значение поставщика больше не предлагается.",
        request=None,
        responses={200: DeskItemDetail, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, pk, False)


class SupplierDeskViewSet(DeskViewSet):
    """Поставщики с предложениями; правка условий предложения — `supply.manage`, цены — ещё и право на цены поставщиков."""

    required_permissions = {
        "create": "supply.manage",
        "partial_update": "supply.manage",
        "create_offer": "supply.manage",
        "partial_update_offer": "supply.manage",
    }
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
        operation_id="catalog_suppliers_create",
        summary="Add a supplier",
        description=(
            "Needs `supply.manage`. Простая карточка компании: название, страна, ИНН или рег. номер нерезидента (хотя "
            "бы одно — 400 `SUPPLIER_ID_REQUIRED`), контакт, валюта цен. Такой ИНН или пара (страна, рег. номер) уже "
            "есть — 409 `SUPPLIER_EXISTS`."
        ),
        request=DeskSupplierIn,
        responses={201: DeskSupplierDetail, 400: REFUSED, 403: FORBIDDEN, 409: REFUSED},
        tags=["Catalog"],
    )
    def create(self, request):
        body = DeskSupplierIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                company = suppliers.save_supplier(Company(), dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(
            suppliers.supplier_detail(self._supplier(company.pk), request.user), status=status.HTTP_201_CREATED
        )

    @extend_schema(
        operation_id="catalog_suppliers_update",
        summary="Edit a supplier",
        description="Needs `supply.manage`. Те же поля, что при создании; приходят только изменённые.",
        request=DeskSupplierIn,
        responses={200: DeskSupplierDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    def partial_update(self, request, pk=None):
        company = self._supplier(pk)
        body = DeskSupplierIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                suppliers.save_supplier(company, dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        return Response(suppliers.supplier_detail(self._supplier(company.pk), request.user))

    @extend_schema(
        operation_id="catalog_suppliers_offer_create",
        summary="Add a supplier price",
        description=(
            "Needs `supply.manage` и право на цены поставщиков (403 `SUPPLIER_PRICES_REQUIRED`). Одна цена на пару "
            "«поставщик — товар»: вторая — 409 `OFFER_EXISTS`."
        ),
        request=DeskOfferCreateIn,
        responses={201: DeskOffer, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: REFUSED},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="offers", url_name="offers")
    def create_offer(self, request, pk=None):
        company = self._supplier(pk)
        body = DeskOfferCreateIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                offer = suppliers.create_offer(company, dict(body.validated_data), request.user)
        except items.ItemError as error:
            return refuse(error)
        from catalog.desk.access import can_view_supplier_prices

        offer.refresh_from_db()
        return Response(
            items.offer_row(offer, show_price=can_view_supplier_prices(request.user)), status=status.HTTP_201_CREATED
        )

    @extend_schema(
        operation_id="catalog_suppliers_offer_history",
        summary="Supplier price history",
        description="Снимки цены, срока действия, базиса и источника; новые сверху. `price` — только с правом на цены.",
        responses={200: DeskOfferHistoryRow(many=True), 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["get"], url_path=r"offers/(?P<offer_id>[0-9]+)/history", url_name="offer-history")
    def offer_history(self, request, pk=None, offer_id=None):
        offer = SupplierOffer.objects.filter(pk=offer_id, supplier_id=pk).first()
        if offer is None:
            raise NotFound()
        return Response(suppliers.offer_history(offer, request.user))

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
            SupplierOffer.objects.select_related("supplier", "product", "currency", "stock_status", "delivery_basis")
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
