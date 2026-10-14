from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from ..models import (
    ActivityLog,
    ActStatus,
    ContractStatus,
    Deal,
    DealStage,
    FulfillmentStatus,
    InvoiceStatus,
    QuoteStatus,
)

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────
from .inlines import QuoteInline

# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────


@admin.register(DealStage, QuoteStatus, ContractStatus, InvoiceStatus, ActStatus, FulfillmentStatus)
class CRMLookupAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15


# ────────────────────────────────────────────
# Deals
# ────────────────────────────────────────────


@admin.register(Deal)
class DealAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("show_deal", "company", "stage_badge", "total_value", "manager", "created_at")
    list_filter = ("stage", "created_at", "manager")
    list_filter_submit = True
    search_fields = ("title", "company__name", "manager__email", "id")
    autocomplete_fields = ["company", "client", "manager", "stage"]
    readonly_fields = ("created_at", "updated_at")
    inlines = [QuoteInline]
    actions = ["mark_closed_lost"]
    list_per_page = 25
    list_select_related = ("company", "stage", "manager")
    warn_unsaved_form = True

    @display(header=True, description=_("Сделка"))
    def show_deal(self, obj):
        title = obj.title or f"Сделка #{obj.pk}"
        return [title, f"#{obj.pk}"]

    @display(
        description=_("Этап"),
        label={
            "Черновик": "info",
            "Ожидание KYC": "warning",
            "Подбор поставщиков": "info",
            "Расчёт цен": "warning",
            "КП отправлено": "info",
            "Договор подписан": "success",
            "Закрыта (выиграна)": "success",
            "Закрыта (проиграна)": "danger",
        },
    )
    def stage_badge(self, obj):
        return obj.stage.name if obj.stage else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    ("company", "client"),
                    ("stage", "manager"),
                ),
            },
        ),
        (
            _("Заметки"),
            {
                "classes": ["tab"],
                "fields": ("notes",),
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

    @superuser_only_action(_("[Emergency] Закрыть как проигранную"))
    def mark_closed_lost(self, request, queryset):
        from .. import services

        updated = services.bulk_close_deals_lost(queryset, actor=request.user)
        self.message_user(request, _("%(count)d сделок закрыто.") % {"count": updated})


# ────────────────────────────────────────────
# Audit (read-only)
# ────────────────────────────────────────────


@admin.register(ActivityLog)
class ActivityLogAdmin(ModelAdmin):
    list_display = ("action", "user", "level_badge", "timestamp")
    list_filter = ("level", "timestamp")
    list_filter_submit = True
    search_fields = ("action", "detail", "user__email")
    readonly_fields = ("action", "detail", "user", "level", "timestamp")
    list_per_page = 50
    list_select_related = ("user",)
    show_full_result_count = False

    @display(
        description=_("Уровень"),
        label={
            "Информация": "info",
            "Успех": "success",
            "Предупреждение": "warning",
            "Ошибка": "danger",
        },
    )
    def level_badge(self, obj):
        return obj.get_level_display()

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("action", "level"),
                    "detail",
                    ("user", "timestamp"),
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
