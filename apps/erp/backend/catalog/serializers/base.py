from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.models import Company
from master_data.models import Currency, DeliveryBasis, UnitOfMeasure

from ..models import (
    Category,
    DomainType,
    Manufacturer,
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


# --- Media Serializers ---


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "image_url", "is_main", "alt_text", "is_public"]


class ProductDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductDocument
        fields = ["id", "file", "file_url", "name", "uploaded_at", "is_public"]


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
