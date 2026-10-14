from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import Product
from .base import (
    CategorySerializer,
    CompanyLightSerializer,
    ProductDocumentSerializer,
    ProductImageSerializer,
    SupplierOfferSerializer,
    UnitOfMeasureSerializer,
)

# --- Main Product Serializer (PIM) ---


#: Кто из сотрудников видит внутренний слой цен (предложения поставщиков, себестоимость):
#: ведущий каталог, закупщик и тот, кому роль даёт себестоимость и маржу КП. Администратор — всегда.
COST_VIEW_PERMISSIONS = ("quote.view_cost_margin", "catalog.manage", "supply.manage")


class _CostGateMixin:
    """Срезает поля себестоимости (`offers` / `base_price`) у тех, кому их видеть нельзя (C1, M1-ERP-07).

    Цены поставщиков — внутренний слой: их видят администратор и сотрудник своей компании с правом
    `quote.view_cost_margin`, `catalog.manage` или `supply.manage`. Клиенту (не-сотруднику) карточка
    этим сериализатором не отдаётся вовсе — только проекцией опубликованного слоя.
    """

    cost_fields: tuple = ()

    def _viewer_sees_cost(self) -> bool:
        if hasattr(self, "_sees_cost"):
            return self._sees_cost
        user = getattr(self.context.get("request"), "user", None)
        from accounts.services.permissions import staff_has_permission

        self._sees_cost = bool(
            user is not None
            and getattr(user, "is_authenticated", False)
            and (getattr(user, "is_superuser", False) or staff_has_permission(user, COST_VIEW_PERMISSIONS))
        )
        return self._sees_cost

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._viewer_sees_cost():
            for field_name in self.cost_fields:
                data.pop(field_name, None)
        return data


class _LayerFieldsMixin:
    """Поля вида и опубликованного слоя, общие для списка и карточки."""

    def get_kind(self, obj) -> str | None:
        return str(obj.kind) if obj.kind else None

    def get_list_price_currency_code(self, obj) -> str | None:
        return obj.list_price_currency.code if obj.list_price_currency_id else None


class ProductSerializer(_CostGateMixin, _LayerFieldsMixin, serializers.ModelSerializer):
    # `base_price_currency` уезжает вместе с ценой: валюта цены, которую зрителю не показали,
    # сама по себе бессмысленна и лишь намекает на скрытое.
    cost_fields = ("offers", "base_price", "base_price_currency")

    # Readable Nested Objects (for GET)
    category_data = CategorySerializer(source="category", read_only=True)
    owner_company_data = CompanyLightSerializer(source="owner_company", read_only=True)
    uom_data = UnitOfMeasureSerializer(source="uom", read_only=True)

    offers = SupplierOfferSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    documents = ProductDocumentSerializer(many=True, read_only=True)

    main_image_url = serializers.SerializerMethodField()
    main_document_url = serializers.SerializerMethodField()

    # Computed display fields
    status_name = serializers.SerializerMethodField()
    status_code = serializers.SerializerMethodField()
    # Полнота ВЫЧИСЛЯЕТСЯ (Akeneo): `missing` называет, чего не хватает, — интерфейс говорит
    # «не хватает: категория, ТН ВЭД» вместо абстрактного процента, а публикация открывается
    # сама, когда обязательное заполнено.
    completeness = serializers.SerializerMethodField()

    def get_completeness(self, obj) -> dict:
        from catalog.completeness import completeness as compute

        return compute(obj)

    domain_type_name = serializers.SerializerMethodField()
    domain_type_code = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    brand_country = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    base_price = serializers.SerializerMethodField()
    base_price_currency = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()
    list_price_currency_code = serializers.SerializerMethodField()
    # «Глазами клиента» (M1-ERP-07): ровно то, что уйдёт клиенту, — той же функцией проекции.
    client_preview = serializers.SerializerMethodField()

    @extend_schema_field(
        {
            "type": "object",
            "description": "Опубликованный слой глазами клиента (`published_projection`, режим client)",
            "additionalProperties": True,
        }
    )
    def get_client_preview(self, obj) -> dict:
        from catalog.services.layers import published_projection

        return published_projection(obj, request=self.context.get("request"))

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "description",
            "kind",
            "fulfillment_policy",
            "visibility",
            "list_price",
            "list_price_currency",
            "list_price_currency_code",
            "client_lead_time_days",
            "internal_notes",
            "client_preview",
            "status",
            "status_name",
            "status_code",
            "completeness",
            "demand_count",
            "last_requested_at",
            "source_deal",
            "domain_type",
            "domain_type_name",
            "domain_type_code",
            "category",
            "category_data",
            "owner_company",
            "owner_company_data",
            "brand",
            "brand_name",
            "brand_country",
            "manufacturer_part_number",
            "uom",
            "uom_data",
            "gost_drawing",
            "hs_code",
            "specifications",
            "offers",
            "images",
            "documents",
            "main_image_url",
            "main_document_url",
            "stock_status",
            "base_price",
            "base_price_currency",
            "created_at",
            "updated_at",
        ]
        # owner_company is stamped by the server (perform_create) and immutable after —
        # making it writable would let a seller PATCH their product to another tenant (M6).
        # status — жизненный цикл, а не поле формы (N2, B4 аудита): записываемый status
        # позволял опубликовать PATCH'ем в обход порога полноты publish_product(). Смена
        # статуса — ТОЛЬКО сервисами (publishing.py, merging.py, Unfold emergency).
        # visibility — решение о показе цены клиенту: только действиями `publish` / `visibility`
        # под правом `catalog.publish` (M1-ERP-07), не правкой формы под `catalog.manage`.
        read_only_fields = ["sku", "created_at", "updated_at", "owner_company", "status", "visibility"]

    def validate(self, attrs):
        """Validate product attributes before create/update."""
        attrs = super().validate(attrs)
        # Бренд на лету (N1): форма шлёт `brand_name` строкой, нормализатор общий с импортом.
        # `brand_name` в чтении — SerializerMethodField, поэтому на запись берём из initial_data;
        # явный `brand` (id) имеет приоритет.
        raw_brand_name = (self.initial_data or {}).get("brand_name")
        if raw_brand_name is not None and "brand" not in (self.initial_data or {}):
            from catalog.services import find_or_create_manufacturer

            attrs["brand"] = find_or_create_manufacturer(str(raw_brand_name))
        return attrs

    def get_status_name(self, obj) -> str | None:
        return obj.status.name if obj.status else None

    def get_status_code(self, obj) -> str | None:
        return obj.status.code if obj.status else None

    def get_domain_type_name(self, obj) -> str | None:
        return obj.domain_type.name if obj.domain_type else None

    def get_domain_type_code(self, obj) -> str | None:
        return obj.domain_type.code if obj.domain_type else None

    def get_brand_name(self, obj) -> str | None:
        return obj.brand.name if obj.brand else None

    def get_brand_country(self, obj) -> str | None:
        return obj.brand.country.name if obj.brand and obj.brand.country else None

    def _first_offer(self, obj):
        """Get first active offer from prefetched data (no extra query)."""
        offers = obj.offers.all()
        active = next((o for o in offers if o.is_active), None)
        return active or next(iter(offers), None)

    def get_stock_status(self, obj) -> str | None:
        offer = self._first_offer(obj)
        if offer and offer.stock_status:
            return offer.stock_status.code
        return None

    def get_base_price(self, obj) -> str | None:
        """Цена ИЛИ `null` — как в списке: «нет оффера» и «стоит ноль» не одно и то же."""
        offer = self._first_offer(obj)
        return str(offer.base_price) if offer else None

    def get_base_price_currency(self, obj) -> str | None:
        """ISO-код валюты ТОГО ЖЕ оффера, что дал `base_price` (иначе `null`).

        Карточка товара печатала цену жёстко в UZS. Поле обязано быть и здесь, а не только
        в списке: без него карточка либо снова врёт валютой, либо не печатает цену вовсе.
        """
        offer = self._first_offer(obj)
        return offer.currency.code if offer and offer.currency_id else None

    def get_main_image_url(self, obj) -> str | None:
        images = obj.images.all()
        main_img = next((i for i in images if i.is_main), None) or next(iter(images), None)
        if main_img:
            url = main_img.image.url if main_img.image else main_img.image_url
            if url:
                request = self.context.get("request")
                if request and not url.startswith("http"):
                    return request.build_absolute_uri(url)
                return url
        return None

    def get_main_document_url(self, obj) -> str | None:
        docs = obj.documents.all()
        doc = next(iter(docs), None)
        if doc:
            url = doc.file.url if doc.file else doc.file_url
            if url:
                request = self.context.get("request")
                if request and not url.startswith("http"):
                    return request.build_absolute_uri(url)
                return url
        return None


class ProductListSerializer(_CostGateMixin, _LayerFieldsMixin, serializers.ModelSerializer):
    """Lightweight serializer for list endpoints — no nested offers/documents."""

    # Полнота нужна ИМЕННО в списке: очередь наполнения продавца показывает, чего не хватает,
    # прямо в строке — иначе пришлось бы открывать каждую карточку, чтобы это узнать.
    completeness = serializers.SerializerMethodField()

    def get_completeness(self, obj) -> dict:
        from catalog.completeness import completeness as compute

        return compute(obj, self._completeness_context(obj))

    def _completeness_context(self, obj):
        """Один `CompletenessContext` на ВЕСЬ проход сериализации страницы, а не на строку.

        DRF переиспользует ОДИН экземпляр дочернего сериализатора для всех элементов
        `many=True`-списка, поэтому память здесь живёт ровно столько, сколько сам ответ.
        `self.root.instance` — это страница пагинатора (список моделей); когда сериализатор
        работает в одиночку (`self.root is self`), контекст строится по одной карточке.
        """
        context = getattr(self, "_completeness_ctx", None)
        if context is None:
            from catalog.completeness import CompletenessContext

            page = getattr(self.root, "instance", None)
            # Модель не итерируема, страница пагинатора и queryset — да; всё остальное
            # честно деградирует до одной карточки (медленнее, но никогда не неверно).
            batch = page if (self.root is not self and hasattr(page, "__iter__")) else None
            products = list(batch) if batch is not None else [obj]
            context = CompletenessContext(products)
            self._completeness_ctx = context
        return context

    # Валюта уходит вместе с ценой: показать «USD» без самой цены — не защита, а бессмыслица
    # (и наоборот, цена без валюты уже врала — фронтенд печатал её как UZS).
    cost_fields = ("base_price", "base_price_currency")

    category_data = CategorySerializer(source="category", read_only=True)
    owner_company_data = CompanyLightSerializer(source="owner_company", read_only=True)
    uom_data = UnitOfMeasureSerializer(source="uom", read_only=True)

    main_image_url = serializers.SerializerMethodField()
    status_name = serializers.SerializerMethodField()
    status_code = serializers.SerializerMethodField()
    domain_type_name = serializers.SerializerMethodField()
    domain_type_code = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    brand_country = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    base_price = serializers.SerializerMethodField()
    base_price_currency = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()
    list_price_currency_code = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "kind",
            "fulfillment_policy",
            "visibility",
            "list_price",
            "list_price_currency_code",
            "status",
            "status_name",
            "status_code",
            "demand_count",
            "completeness",
            "last_requested_at",
            "source_deal",
            "domain_type",
            "domain_type_name",
            "domain_type_code",
            "category",
            "category_data",
            "owner_company",
            "owner_company_data",
            "brand",
            "brand_name",
            "brand_country",
            "manufacturer_part_number",
            "uom",
            "uom_data",
            "gost_drawing",
            "hs_code",
            "main_image_url",
            "stock_status",
            "base_price",
            "base_price_currency",
            "created_at",
            "updated_at",
        ]

    def get_status_name(self, obj) -> str | None:
        return obj.status.name if obj.status else None

    def get_status_code(self, obj) -> str | None:
        return obj.status.code if obj.status else None

    def get_domain_type_name(self, obj) -> str | None:
        return obj.domain_type.name if obj.domain_type else None

    def get_domain_type_code(self, obj) -> str | None:
        return obj.domain_type.code if obj.domain_type else None

    def get_brand_name(self, obj) -> str | None:
        return obj.brand.name if obj.brand else None

    def get_brand_country(self, obj) -> str | None:
        return obj.brand.country.name if obj.brand and obj.brand.country else None

    def _first_offer(self, obj):
        """Первый АКТИВНЫЙ оффер из предзагруженных, иначе любой.

        `SupplierOffer.Meta.ordering = ["base_price"]`, то есть это САМЫЙ ДЕШЁВЫЙ оффер —
        поведение сознательное и неизменное. Цену и валюту обязан отдавать ОДИН И ТОТ ЖЕ
        объект: второй проход мог бы выбрать другой оффер и склеить цену с чужой валютой.
        """
        offers = obj.offers.all()
        active = next((o for o in offers if o.is_active), None)
        return active or next(iter(offers), None)

    def get_stock_status(self, obj) -> str | None:
        offer = self._first_offer(obj)
        return offer.stock_status.code if offer and offer.stock_status else None

    def get_base_price(self, obj) -> str | None:
        """Цена ИЛИ `null` — «нет оффера» и «стоит ноль» не одно и то же.

        Строка "0" рендерилась как настоящая цена и делала карточку без единого предложения
        похожей на бесплатную (Odoo/Shopify так же различают «нет прайса» и «цена 0»).
        """
        offer = self._first_offer(obj)
        return str(offer.base_price) if offer else None

    def get_base_price_currency(self, obj) -> str | None:
        """ISO-код валюты ТОГО ЖЕ оффера, что дал `base_price` (иначе `null`).

        Без него список печатал любую цену как UZS — долларовый оффер выглядел дешевле
        собственной цены в 12 тысяч раз.
        """
        offer = self._first_offer(obj)
        return offer.currency.code if offer and offer.currency_id else None

    def get_main_image_url(self, obj) -> str | None:
        images = obj.images.all()
        main_img = next((i for i in images if i.is_main), None) or next(iter(images), None)
        if main_img:
            url = main_img.image.url if main_img.image else main_img.image_url
            if url:
                request = self.context.get("request")
                if request and not url.startswith("http"):
                    return request.build_absolute_uri(url)
                return url
        return None
