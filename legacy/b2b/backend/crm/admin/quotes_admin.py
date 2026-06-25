from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from ..models import Quote, QuoteItemHistory

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────
from .inlines import QuoteItemInline

# ────────────────────────────────────────────
# Quotes
# ────────────────────────────────────────────


@admin.register(Quote)
class QuoteAdmin(ModelAdmin):
    list_display = ("deal", "version", "quote_status", "total_incl_vat", "prepared_by", "created_at")
    list_filter = ("status", "created_at", "tax_country")
    list_filter_submit = True
    search_fields = ("deal__title", "deal__company__name")
    inlines = [QuoteItemInline]
    # ADR-0002 / Rule 8: Unfold is oversight-only. The platform engineer must NEVER author or
    # re-price a company's КП — all quote/line writes go through React Admin + crm.services.
    # Every business field is read-only here; the screen stays VIEWABLE for debug/inspection.
    readonly_fields = [
        "deal",
        "version",
        "status",
        "prepared_by",
        "tax_country",
        "vat_rate",
        "valid_until",
        "notes",
        "approved_by",
        "subtotal_excl_vat",
        "vat_amount",
        "total_incl_vat",
        "frozen_at",
        "approved_at",
        "created_at",
        "updated_at",
    ]
    list_per_page = 25
    list_select_related = ("deal", "status", "prepared_by")
    warn_unsaved_form = True

    @display(
        description=_("Статус"),
        label={
            "Черновик": "warning",
            "Отправлено клиенту": "info",
            "Одобрено клиентом": "success",
            "Отклонено": "danger",
            "Срок истёк": "danger",
        },
    )
    def quote_status(self, obj):
        return obj.status.name if obj.status else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("deal", "version"),
                    ("status", "prepared_by"),
                ),
            },
        ),
        (
            _("Суммы"),
            {
                "classes": ["tab"],
                "fields": (
                    ("tax_country", "vat_rate"),
                    ("subtotal_excl_vat", "vat_amount", "total_incl_vat"),
                ),
            },
        ),
        (
            _("Сроки"),
            {
                "classes": ["tab"],
                "fields": (
                    "valid_until",
                    "notes",
                    ("frozen_at", "approved_at"),
                    "approved_by",
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuoteItemHistory)
class QuoteItemHistoryAdmin(ModelAdmin):
    list_display = (
        "quote_item",
        "changed_by",
        "frozen_base_price",
        "margin_percent",
        "final_price_excl_vat",
        "quantity",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("quote_item__product__name", "changed_by__email", "change_reason")
    readonly_fields = (
        "quote_item",
        "changed_by",
        "frozen_base_price",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "landed_cost",
        "final_price_excl_vat",
        "quantity",
        "change_reason",
        "created_at",
    )
    list_per_page = 30
    list_select_related = ("quote_item", "quote_item__product", "changed_by")
    show_full_result_count = False

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("quote_item", "changed_by"),
                    ("change_reason", "created_at"),
                ),
            },
        ),
        (
            _("Финансовый снимок"),
            {
                "classes": ["tab"],
                "fields": (
                    ("frozen_base_price", "logistics_cost", "customs_duty"),
                    ("margin_percent", "landed_cost", "final_price_excl_vat"),
                    "quantity",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
