from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.reverse import reverse

from accounts.models import Company
from master_data.models import Currency, DeliveryBasis, UnitOfMeasure

from .models import (
    Category,
    DomainType,
    Manufacturer,
    Product,
    ProductDocument,
    ProductImage,
    ProductStatus,
    StockStatus,
    SupplierOffer,
)


class CompanyLightSerializer(serializers.ModelSerializer):
    """Lightweight company serializer for nested use — no extra queries."""

    class Meta:
        model = Company
        fields = ["id", "name", "inn", "logo"]


class ManufacturerSerializer(serializers.ModelSerializer):
    """OEM brand lookup (catalog.Manufacturer) — the canonical `Product.brand` source.

    NOT a platform participant (that's the seller/owner). A brand needn't have an
    account; `company` optionally links it to one if the OEM is registered."""

    country_name = serializers.SerializerMethodField()

    @extend_schema_field({"type": "string"})
    def get_country_name(self, obj) -> str:
        # Не `CharField(source=…, default=None)`: при PATCH (partial) DRF пропускает такое поле, и ответ теряет ключ.
        # Пустая строка, а не null: схема всегда обещала строку (null в ответе нарушал её, а oasdiff считает nullable ломающим).
        return obj.country.name if obj.country_id else ""

    class Meta:
        model = Manufacturer
        fields = ["id", "name", "country", "country_name", "website", "company", "is_active"]


# --- Simple Reference Serializers ---


class DomainTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainType
        fields = ["id", "code", "name", "sku_prefix", "sort_order", "is_active"]


class ProductStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductStatus
        fields = ["id", "code", "name"]


class StockStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockStatus
        fields = ["id", "code", "name"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "parent", "domain_type", "icon"]


@extend_schema_serializer(component_name="CatalogUnitOfMeasure")
class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ["id", "code", "name"]


@extend_schema_serializer(component_name="CatalogCurrency")
class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["id", "code", "symbol"]


@extend_schema_serializer(component_name="CatalogDeliveryBasis")
class DeliveryBasisSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryBasis
        fields = ["id", "code", "name", "description"]


# --- Media Serializers ---


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "image_url", "is_main", "alt_text"]


class ProductDocumentSerializer(serializers.ModelSerializer):
    # Файл документа приватный (S0-9): вместо адреса в хранилище — путь аутентифицированного скачивания
    # (`GET catalog/products/{id}/download-document/{doc_id}/`, поток с проверкой прав); нет файла — null.
    file = serializers.SerializerMethodField()

    class Meta:
        model = ProductDocument
        fields = ["id", "file", "file_url", "name", "uploaded_at"]

    @extend_schema_field(
        {"type": "string", "nullable": True, "description": "Путь скачивания файла (API), null — файла нет"}
    )
    def get_file(self, obj):
        if not obj.file:
            return None
        return reverse("product-download-document", kwargs={"pk": obj.product_id, "doc_id": obj.pk})


# --- Supplier Offer Serializer ---


class SupplierOfferSerializer(serializers.ModelSerializer):
    supplier_data = CompanyLightSerializer(source="supplier", read_only=True)
    currency_data = CurrencySerializer(source="currency", read_only=True)
    delivery_basis_data = DeliveryBasisSerializer(source="delivery_basis", read_only=True)

    class Meta:
        model = SupplierOffer
        fields = [
            "id",
            "product",
            "supplier",
            "supplier_data",
            "supplier_sku",
            "base_price",
            "currency",
            "currency_data",
            "delivery_basis",
            "delivery_basis_data",
            "stock_status",
            "delivery_lead_time",
            "stock_quantity",
            "in_stock_lead_time_days",
            "order_lead_time_days",
            "min_order_qty",
            # R7: окно действия цены было в модели, но не в контракте — задать срок было
            # негде, и «цена до конца квартала» жила в переписке, а не в карточке.
            "valid_from",
            "valid_until",
            "is_active",
        ]

    def validate(self, attrs):
        """Окно действия цены проверяется ЦЕЛИКОМ, включая частичное обновление.

        На PATCH в теле приходит одна граница из двух — сравнивать её надо со второй,
        уже сохранённой, иначе перевёрнутое окно собиралось бы двумя запросами.
        """
        attrs = super().validate(attrs)
        instance = self.instance
        valid_from = attrs.get("valid_from", getattr(instance, "valid_from", None))
        valid_until = attrs.get("valid_until", getattr(instance, "valid_until", None))
        from catalog.services import offer_validity_error

        error = offer_validity_error(valid_from, valid_until)
        if error:
            raise serializers.ValidationError({"detail": error})
        return attrs


# --- Published layer (M1-ERP-07) ---


class _MoneySerializer(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class _AttributeSerializer(serializers.Serializer):
    name = serializers.CharField()
    value = serializers.CharField()


class PublishedCatalogItemSerializer(serializers.Serializer):
    """Схема OpenAPI проекции `catalog.published.project` (контракт портала `CatalogItem`).

    Только для документации: данные собирает `project()` белым списком, не этот класс.
    """

    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["goods", "service"])
    name = serializers.CharField()
    description = serializers.CharField()
    unit = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    price = _MoneySerializer(allow_null=True, required=False)
    availability = serializers.ChoiceField(choices=["in_stock", "on_order", "expected"], required=False)
    lead_time_days = serializers.IntegerField(allow_null=True, required=False)
    images = serializers.ListField(child=serializers.CharField())
    attributes = _AttributeSerializer(many=True)


# --- Main Product Serializer (PIM) ---


class _CostGateMixin:
    """Strip supplier-cost fields (offers / base_price) from viewers who don't own
    the product. Only the OWNING seller's team + platform admins see cost & supplier
    identity — clients, other sellers and anon never do (C1 cost-leak fix). React was
    only hiding these client-side; the data still travelled in the API response.
    """

    cost_fields: tuple = ()

    def _viewer_company_ids(self):
        if hasattr(self, "_vci"):
            return self._vci
        user = getattr(self.context.get("request"), "user", None)
        ids = set()
        if user is not None and getattr(user, "is_authenticated", False):
            ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        self._vci = ids
        return ids

    def _viewer_owns_or_admin(self, obj) -> bool:
        user = getattr(self.context.get("request"), "user", None)
        if not (user is not None and getattr(user, "is_authenticated", False)):
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "is_superuser", False):
            return True
        owner_id = getattr(obj, "owner_company_id", None)
        return bool(owner_id and owner_id in self._viewer_company_ids())

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._viewer_owns_or_admin(instance):
            for field_name in self.cost_fields:
                data.pop(field_name, None)
        return data


class ProductSerializer(_CostGateMixin, serializers.ModelSerializer):
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

    # ── Опубликованный слой (M1-ERP-07) ───────────────────────────────────────
    list_price_currency_code = serializers.CharField(
        source="list_price_currency.code", read_only=True, allow_null=True, default=None
    )
    price_visibility_effective = serializers.SerializerMethodField()
    price_visibility_default = serializers.SerializerMethodField()
    client_preview = serializers.SerializerMethodField()

    def _policy(self, obj):
        from catalog.policy import policy_for

        cache = self.__dict__.setdefault("_policy_cache", {})
        if obj.owner_company_id not in cache:
            cache[obj.owner_company_id] = policy_for(obj.owner_company_id)
        return cache[obj.owner_company_id]

    def get_price_visibility_effective(self, obj) -> str:
        """Видимость цены с учётом политики компании — то, что реально увидит клиент."""
        from catalog.policy import effective_price_visibility

        return effective_price_visibility(obj, self._policy(obj))

    def get_price_visibility_default(self, obj) -> str:
        """Политика каталога компании — подпись варианта «как в политике каталога» в форме."""
        return self._policy(obj).price_visibility

    @extend_schema_field(PublishedCatalogItemSerializer)
    def get_client_preview(self, obj) -> dict:
        """«Так карточку видит клиент» — та же проекция, что отдаёт портал (`catalog.published`).

        Сотрудник видит превью прямо в карточке и не гадает, что из внутреннего слоя уйдёт
        наружу: ровно ничего, кроме этих полей.
        """
        from catalog.constants import MODE_CLIENT
        from catalog.published import project

        return project(obj, mode=MODE_CLIENT, policy=self._policy(obj), request=self.context.get("request"))

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "description",
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
            "fulfillment_policy",
            "price_visibility",
            "price_visibility_effective",
            "price_visibility_default",
            "list_price",
            "list_price_currency",
            "list_price_currency_code",
            "client_preview",
            "created_at",
            "updated_at",
        ]
        # owner_company is stamped by the server (perform_create) and immutable after —
        # making it writable would let a seller PATCH their product to another tenant (M6).
        # status — жизненный цикл, а не поле формы (N2, B4 аудита): записываемый status
        # позволял опубликовать PATCH'ем в обход порога полноты publish_product(). Смена
        # статуса — ТОЛЬКО сервисами (publishing.py, merging.py, Unfold emergency).
        read_only_fields = ["sku", "created_at", "updated_at", "owner_company", "status"]

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
        # Цена-витрина без валюты — не цена (Money = amount + currency). Проверяем итог с учётом
        # уже сохранённого: PATCH может прислать одно из двух полей.
        instance = self.instance
        list_price = attrs.get("list_price", getattr(instance, "list_price", None))
        currency = attrs.get("list_price_currency", getattr(instance, "list_price_currency", None))
        if list_price is not None and currency is None:
            raise serializers.ValidationError({"list_price_currency": "LIST_PRICE_CURRENCY_REQUIRED"})
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
            # Загруженный файл приватный (S0-9): `/media/...` для него не открывается — отдаём путь аутентифицированного скачивания.
            url = (
                reverse("product-download-document", kwargs={"pk": doc.product_id, "doc_id": doc.pk})
                if doc.file
                else doc.file_url
            )
            if url:
                request = self.context.get("request")
                if request and not url.startswith("http"):
                    return request.build_absolute_uri(url)
                return url
        return None


class ProductListSerializer(_CostGateMixin, serializers.ModelSerializer):
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

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
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
