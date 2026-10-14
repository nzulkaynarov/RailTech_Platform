from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.decorators import display

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from .models import (
    Category,
    CategoryRequest,
    DomainType,
    Manufacturer,
    Product,
    ProductDocument,
    ProductImage,
    ProductStatus,
    StockStatus,
    SupplierOffer,
)
from .resources import ProductResource, SupplierOfferResource

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────


class SupplierOfferInline(TabularInline):
    model = SupplierOffer
    extra = 0
    tab = True
    fields = ("supplier", "base_price", "currency", "stock_status", "is_active")
    autocomplete_fields = ["supplier", "currency", "stock_status"]


class ProductImageInline(TabularInline):
    model = ProductImage
    extra = 0
    tab = True
    fields = ("image", "image_url", "is_main", "alt_text")


class ProductDocumentInline(TabularInline):
    model = ProductDocument
    extra = 0
    tab = True
    fields = ("file", "file_url", "name")


# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────


@admin.register(DomainType)
class DomainTypeAdmin(ModelAdmin):
    list_display = ["name", "code", "sku_prefix", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15

    fieldsets = (
        (
            None,
            {
                "fields": (("name", "code"), ("sku_prefix", "sort_order"), "is_active"),
            },
        ),
    )


@admin.register(ProductStatus, StockStatus)
class CatalogLookupAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15


# ────────────────────────────────────────────
# Hierarchy
# ────────────────────────────────────────────


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("name", "domain_type", "parent", "sort_order", "is_active")
    list_filter = ("is_active", "domain_type")
    list_filter_submit = True
    search_fields = ("name",)
    autocomplete_fields = ["parent", "domain_type"]
    list_editable = ["sort_order", "is_active"]
    list_per_page = 30
    list_select_related = ("domain_type", "parent")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "domain_type"),
                    "parent",
                    ("icon", "sort_order", "is_active"),
                ),
            },
        ),
    )


@admin.register(Manufacturer)
class ManufacturerAdmin(ModelAdmin):
    list_display = ("name", "country", "company", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("name",)
    list_per_page = 30
    list_select_related = ("country", "company")


# ────────────────────────────────────────────
# Products (PIM)
# ────────────────────────────────────────────


@admin.register(Product)
class ProductAdmin(ReadOnlyInspectionMixin, ImportExportModelAdmin, ModelAdmin):
    resource_classes = [ProductResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("show_product", "domain_badge", "status_badge", "category", "brand")
    list_filter = ("domain_type", "status", "category")
    list_filter_submit = True
    search_fields = ("name", "sku", "gost_drawing")
    readonly_fields = ("sku", "created_at", "updated_at")
    autocomplete_fields = [
        "domain_type",
        "status",
        "category",
        "uom",
        "owner_company",
        "brand",
    ]
    inlines = [SupplierOfferInline, ProductImageInline, ProductDocumentInline]
    actions = ["publish_products"]
    list_per_page = 25
    list_select_related = ("domain_type", "status", "category", "owner_company", "brand")
    show_full_result_count = False
    warn_unsaved_form = True

    @display(header=True, description=_("Товар"))
    def show_product(self, obj):
        return [obj.name, obj.sku or "—"]

    @display(
        description=_("Домен"),
        label={
            "Ж/Д техника и запчасти": "info",
            "Общие промышленные товары": "success",
            "Услуги (логистика, ремонт)": "warning",
        },
    )
    def domain_badge(self, obj):
        return obj.domain_type.name if obj.domain_type else "—"

    @display(
        description=_("Статус"),
        label={"Черновик": "warning", "Опубликован": "success", "В архиве": "danger"},
    )
    def status_badge(self, obj):
        return obj.status.name if obj.status else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "sku"),
                    ("domain_type", "status"),
                    ("category", "uom"),
                ),
            },
        ),
        (
            _("Характеристики"),
            {
                "classes": ["tab"],
                "fields": (
                    "description",
                    ("brand", "owner_company"),
                    "gost_drawing",
                    "specifications",
                ),
            },
        ),
        (
            _("Системное"),
            {
                "classes": ["tab"],
                "fields": (("created_at", "updated_at"),),
            },
        ),
    )

    @superuser_only_action(_("[Emergency] Опубликовать (PUBLISHED)"))
    def publish_products(self, request, queryset):
        from . import services

        updated, skipped = services.publish_products(queryset)
        if skipped:
            names = ", ".join(skipped[:5])
            self.message_user(request, _("Не опубликовано: %(names)s") % {"names": names}, level="error")
        if updated:
            self.message_user(request, _("%(count)d опубликовано.") % {"count": updated})


# ────────────────────────────────────────────
# Supplier Offers
# ────────────────────────────────────────────


@admin.register(SupplierOffer)
class SupplierOfferAdmin(ReadOnlyInspectionMixin, ImportExportModelAdmin, ModelAdmin):
    resource_classes = [SupplierOfferResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("product", "supplier", "base_price", "currency", "stock_badge", "is_active")
    list_filter = ("is_active", "currency", "stock_status", "delivery_basis")
    list_filter_submit = True
    search_fields = ("product__name", "supplier__name", "supplier_sku")
    autocomplete_fields = ["product", "supplier", "currency", "delivery_basis", "stock_status"]
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    list_select_related = ("product", "supplier", "currency", "stock_status")
    show_full_result_count = False
    warn_unsaved_form = True

    @display(
        description=_("Наличие"),
        label={
            "В наличии": "success",
            "Под заказ": "warning",
            "Ожидается": "info",
            "Нет в наличии": "danger",
        },
    )
    def stock_badge(self, obj):
        return obj.stock_status.name if obj.stock_status else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("product", "supplier"),
                    "supplier_sku",
                ),
            },
        ),
        (
            _("Цена и условия"),
            {
                "classes": ["tab"],
                "fields": (
                    ("base_price", "currency"),
                    ("delivery_basis", "stock_status"),
                    ("delivery_lead_time", "min_order_qty"),
                    "stock_quantity",
                    ("in_stock_lead_time_days", "order_lead_time_days"),
                ),
            },
        ),
        (
            _("Срок действия"),
            {
                "classes": ["tab"],
                "fields": (
                    ("valid_from", "valid_until"),
                    "is_active",
                    ("created_at", "updated_at"),
                ),
            },
        ),
    )


# ────────────────────────────────────────────
# Заявки на категорию (R6) — ТОЛЬКО инспекция
# ────────────────────────────────────────────


@admin.register(CategoryRequest)
class CategoryRequestAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """Просмотр обращений инженером. Рассматривают их в операторской плоскости (ADR-0001).

    Кнопки «одобрить/отклонить» здесь СОЗНАТЕЛЬНО отсутствуют: решение по заявке — бизнес-
    действие со side-effect'ами (аудит, уведомление автору, привязка категории), и его место —
    DRF-эндпоинт `catalog/category-requests/{id}/approve|reject/`, вызывающий сервис. Дублировать
    его @admin.action'ом запрещено (Rule 8).
    """

    list_display = ("proposed_name", "company", "status", "resulting_category", "created_at")
    list_filter = ("status", "domain_type")
    list_filter_submit = True
    search_fields = ("proposed_name", "company__name")
    list_select_related = ("company", "parent", "domain_type", "resulting_category")
    readonly_fields = ("created_at", "updated_at", "reviewed_at")
    list_per_page = 30
