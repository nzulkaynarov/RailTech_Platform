from django.utils.translation import gettext_lazy
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.models import Company
from master_data.models import Currency, DeliveryBasis, UnitOfMeasure

from .models import (
    Category,
    DomainType,
    EquipmentGroup,
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

    country_name = serializers.CharField(source="country.name", read_only=True, default=None)

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


class EquipmentGroupSerializer(serializers.ModelSerializer):
    full_path = serializers.CharField(read_only=True)

    class Meta:
        model = EquipmentGroup
        fields = ["id", "name", "full_path"]


# --- Media Serializers ---


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "image_url", "is_main", "alt_text"]


class ProductDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductDocument
        fields = ["id", "file", "file_url", "name", "uploaded_at"]


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


# --- Main Product Serializer (PIM) ---


class _CostGateMixin:
    """Strip supplier-cost fields (offers / base_price) from viewers who don't own
    the product. Only the OWNING seller's team + platform admins see cost & supplier
    identity — buyers, other sellers and anon never do (C1 cost-leak fix). React was
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
    equipment_groups_data = EquipmentGroupSerializer(source="equipment_groups", many=True, read_only=True)

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
            "equipment_groups",
            "equipment_groups_data",
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
        read_only_fields = ["sku", "created_at", "updated_at", "owner_company", "status"]

    def validate(self, attrs):
        """Enforce the RAILWAY_MACHINERY "≥1 equipment group" rule at the API layer (H5).

        ``Product.clean()`` skips the check when ``pk is None`` (the m2m can't be
        read before the row exists) and an empty m2m fires no ``m2m_changed`` signal,
        so an API *create* without groups would otherwise persist a silently-invalid
        card. We validate here so the request gets a clean 400 instead.
        """
        attrs = super().validate(attrs)
        # Бренд на лету (N1): форма шлёт `brand_name` строкой, нормализатор общий с импортом.
        # `brand_name` в чтении — SerializerMethodField, поэтому на запись берём из initial_data;
        # явный `brand` (id) имеет приоритет.
        raw_brand_name = (self.initial_data or {}).get("brand_name")
        if raw_brand_name is not None and "brand" not in (self.initial_data or {}):
            from catalog.services import find_or_create_manufacturer

            attrs["brand"] = find_or_create_manufacturer(str(raw_brand_name))
        domain_type = attrs.get("domain_type")
        # On partial update domain_type may be absent — fall back to the instance.
        if domain_type is None and self.instance is not None:
            domain_type = self.instance.domain_type
        is_railway = bool(domain_type) and getattr(domain_type, "code", None) == "RAILWAY_MACHINERY"
        if not is_railway:
            return attrs
        from catalog.services import equipment_groups_available

        # Пустой справочник групп не блокирует сохранение (канон ТН ВЭД, N1).
        if not equipment_groups_available():
            return attrs

        # equipment_groups present in the payload? use it; else fall back to the
        # instance's current groups (partial update that doesn't touch groups).
        if "equipment_groups" in attrs:
            groups = attrs.get("equipment_groups") or []
        elif self.instance is not None:
            groups = list(self.instance.equipment_groups.all())
        else:
            groups = []
        if not groups:
            raise serializers.ValidationError(
                {
                    "equipment_groups": gettext_lazy(
                        "Товары домена RAILWAY_MACHINERY должны быть привязаны минимум к одной группе оборудования."
                    )
                }
            )
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
