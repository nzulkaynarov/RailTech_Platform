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


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ["id", "code", "name"]


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["id", "code", "symbol"]


class DeliveryBasisSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryBasis
        fields = ["id", "code", "name", "description"]


class EquipmentGroupSerializer(serializers.ModelSerializer):
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
            "min_order_qty",
            "is_active",
        ]


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
        if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
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
    cost_fields = ("offers", "base_price")

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
    domain_type_name = serializers.SerializerMethodField()
    domain_type_code = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    brand_country = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    base_price = serializers.SerializerMethodField()

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["sku", "created_at", "updated_at"]

    def get_status_name(self, obj):
        return obj.status.name if obj.status else None

    def get_status_code(self, obj):
        return obj.status.code if obj.status else None

    def get_domain_type_name(self, obj):
        return obj.domain_type.name if obj.domain_type else None

    def get_domain_type_code(self, obj):
        return obj.domain_type.code if obj.domain_type else None

    def get_brand_name(self, obj):
        return obj.brand.name if obj.brand else None

    def get_brand_country(self, obj):
        return obj.brand.country.name if obj.brand and obj.brand.country else None

    def _first_offer(self, obj):
        """Get first active offer from prefetched data (no extra query)."""
        offers = obj.offers.all()
        active = next((o for o in offers if o.is_active), None)
        return active or next(iter(offers), None)

    def get_stock_status(self, obj):
        offer = self._first_offer(obj)
        if offer and offer.stock_status:
            return offer.stock_status.code
        return None

    def get_base_price(self, obj):
        offer = self._first_offer(obj)
        if offer:
            return str(offer.base_price)
        return "0"

    def get_main_image_url(self, obj):
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

    def get_main_document_url(self, obj):
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

    cost_fields = ("base_price",)

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

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "status",
            "status_name",
            "status_code",
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
            "main_image_url",
            "stock_status",
            "base_price",
            "created_at",
            "updated_at",
        ]

    def get_status_name(self, obj):
        return obj.status.name if obj.status else None

    def get_status_code(self, obj):
        return obj.status.code if obj.status else None

    def get_domain_type_name(self, obj):
        return obj.domain_type.name if obj.domain_type else None

    def get_domain_type_code(self, obj):
        return obj.domain_type.code if obj.domain_type else None

    def get_brand_name(self, obj):
        return obj.brand.name if obj.brand else None

    def get_brand_country(self, obj):
        return obj.brand.country.name if obj.brand and obj.brand.country else None

    def _first_offer(self, obj):
        offers = obj.offers.all()
        active = next((o for o in offers if o.is_active), None)
        return active or next(iter(offers), None)

    def get_stock_status(self, obj):
        offer = self._first_offer(obj)
        return offer.stock_status.code if offer and offer.stock_status else None

    def get_base_price(self, obj):
        offer = self._first_offer(obj)
        return str(offer.base_price) if offer else "0"

    def get_main_image_url(self, obj):
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
