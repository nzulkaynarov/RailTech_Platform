from django.utils.translation import gettext_lazy as _
from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget

from accounts.models import Company
from master_data.models import Currency, DeliveryBasis, UnitOfMeasure

from .models import Category, DomainType, Manufacturer, Product, ProductStatus, SupplierOffer


class ProductResource(resources.ModelResource):
    """
    Import/Export ресурс для массовой загрузки товаров.

    Поддерживаемые форматы: XLSX, CSV, JSON.
    FK-поля резолвятся по name или code.
    """

    domain_type = fields.Field(
        column_name=_("Тип домена (код)"),
        attribute="domain_type",
        widget=ForeignKeyWidget(DomainType, field="code"),
    )
    status = fields.Field(
        column_name=_("Статус (код)"),
        attribute="status",
        widget=ForeignKeyWidget(ProductStatus, field="code"),
    )
    category = fields.Field(
        column_name=_("Категория"),
        attribute="category",
        widget=ForeignKeyWidget(Category, field="name"),
    )
    uom = fields.Field(
        column_name=_("Ед. измерения (код)"),
        attribute="uom",
        widget=ForeignKeyWidget(UnitOfMeasure, field="code"),
    )
    brand = fields.Field(
        column_name=_("Бренд / производитель (название)"),
        attribute="brand",
        widget=ForeignKeyWidget(Manufacturer, field="name"),
    )
    # MPN (the brand+MPN PIM dedup key) and HS code are plain CharFields — without
    # them the import/export round-trips drop the dedup key and the customs code
    # (M9). Column names match the XLSX import template (M10) for a clean round-trip.
    manufacturer_part_number = fields.Field(
        column_name="manufacturer_part_number",
        attribute="manufacturer_part_number",
    )
    hs_code = fields.Field(
        column_name="hs_code",
        attribute="hs_code",
    )

    class Meta:
        model = Product
        import_id_fields = ["sku"]
        fields = (
            "sku",
            "name",
            "description",
            "domain_type",
            "status",
            "category",
            "uom",
            "brand",
            "manufacturer_part_number",
            "gost_drawing",
            "hs_code",
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = True


class SupplierOfferResource(resources.ModelResource):
    """
    Import/Export ресурс для массовой загрузки офферов поставщиков.

    FK-поля резолвятся по sku (Product), inn (Company), code (справочники).
    """

    product = fields.Field(
        column_name=_("Товар (SKU)"),
        attribute="product",
        widget=ForeignKeyWidget(Product, field="sku"),
    )
    supplier = fields.Field(
        column_name=_("Поставщик (ИНН)"),
        attribute="supplier",
        widget=ForeignKeyWidget(Company, field="inn"),
    )
    currency = fields.Field(
        column_name=_("Валюта (код)"),
        attribute="currency",
        widget=ForeignKeyWidget(Currency, field="code"),
    )
    delivery_basis = fields.Field(
        column_name=_("Базис поставки (код)"),
        attribute="delivery_basis",
        widget=ForeignKeyWidget(DeliveryBasis, field="code"),
    )

    class Meta:
        model = SupplierOffer
        import_id_fields = ["product", "supplier"]
        fields = (
            "product",
            "supplier",
            "supplier_sku",
            "base_price",
            "currency",
            "delivery_basis",
            "delivery_lead_time",
            "min_order_qty",
            "valid_from",
            "valid_until",
            "is_active",
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = True
