from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from .models import (
    DealStage, QuoteStatus, Deal, Quote, QuoteItem,
    Message, Lead, ActivityLog, QuoteItemHistory
)


# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────

class QuoteItemInline(TabularInline):
    model = QuoteItem
    extra = 0
    tab = True
    autocomplete_fields = ["product", "offer", "frozen_currency"]
    fields = [
        "product", "imported_raw_name", "quantity",
        "frozen_base_price", "logistics_cost", "customs_duty",
        "margin_percent", "landed_cost", "final_price_excl_vat",
    ]
    readonly_fields = ["landed_cost", "final_price_excl_vat"]


class QuoteInline(TabularInline):
    model = Quote
    extra = 0
    tab = True
    show_change_link = True
    fields = ["version", "status", "total_incl_vat", "created_at"]
    readonly_fields = ["version", "status", "total_incl_vat", "created_at"]


# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────

@admin.register(DealStage, QuoteStatus)
class CRMLookupAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15


# ────────────────────────────────────────────
# Deals
# ────────────────────────────────────────────

@admin.register(Deal)
class DealAdmin(ModelAdmin):
    list_display = ("show_deal", "company", "stage_badge", "total_value", "manager", "created_at")
    list_filter = ("stage", "created_at", "manager")
    list_filter_submit = True
    search_fields = ("title", "company__name", "manager__email", "id")
    autocomplete_fields = ["company", "client", "manager", "stage"]
    readonly_fields = ("created_at", "updated_at")
    inlines = [QuoteInline]
    actions = ["mark_closed_lost"]
    list_per_page = 25
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
        (None, {
            "fields": (
                "title",
                ("company", "client"),
                ("stage", "manager"),
            ),
        }),
        (_("Заметки"), {
            "classes": ["tab"],
            "fields": ("notes",),
        }),
        (_("Системное"), {
            "classes": ["tab"],
            "fields": (("created_at", "updated_at"),),
        }),
    )

    @admin.action(description=_("Закрыть как проигранную"))
    def mark_closed_lost(self, request, queryset):
        lost = DealStage.objects.filter(code='CLOSED_LOST').first()
        if not lost:
            self.message_user(request, _("CLOSED_LOST не найдена!"), level="error")
            return
        updated = queryset.exclude(stage__code__in=['CLOSED_WON', 'CLOSED_LOST']).update(stage=lost)
        self.message_user(request, _("%(count)d сделок закрыто.") % {"count": updated})


# ────────────────────────────────────────────
# Quotes
# ────────────────────────────────────────────

@admin.register(Quote)
class QuoteAdmin(ModelAdmin):
    list_display = ("deal", "version", "quote_status", "total_incl_vat", "prepared_by", "created_at")
    list_filter = ("status", "created_at", "tax_country")
    list_filter_submit = True
    search_fields = ("deal__title", "deal__company__name")
    autocomplete_fields = ["deal", "status", "prepared_by", "tax_country", "approved_by"]
    inlines = [QuoteItemInline]
    readonly_fields = [
        "subtotal_excl_vat", "vat_amount", "total_incl_vat",
        "frozen_at", "approved_at", "created_at", "updated_at",
    ]
    list_per_page = 25
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
        (None, {
            "fields": (
                ("deal", "version"),
                ("status", "prepared_by"),
            ),
        }),
        (_("Суммы"), {
            "classes": ["tab"],
            "fields": (
                ("tax_country", "vat_rate"),
                ("subtotal_excl_vat", "vat_amount", "total_incl_vat"),
            ),
        }),
        (_("Сроки"), {
            "classes": ["tab"],
            "fields": (
                "valid_until",
                "notes",
                ("frozen_at", "approved_at"),
                "approved_by",
            ),
        }),
        (_("Системное"), {
            "classes": ["tab"],
            "fields": (("created_at", "updated_at"),),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if "frozen_at" not in readonly:
            readonly.append("frozen_at")
        return readonly

    def save_formset(self, request, form, formset, change):
        formset.save()
        form.instance.recalculate_totals()


# ────────────────────────────────────────────
# Leads
# ────────────────────────────────────────────

@admin.register(Lead)
class LeadAdmin(ModelAdmin):
    list_display = ("name", "company", "email", "phone", "processed_badge", "created_at")
    list_filter = ("is_processed", "created_at")
    list_filter_submit = True
    search_fields = ("name", "company", "email", "phone")
    readonly_fields = ("created_at",)
    actions = ["mark_processed"]
    list_per_page = 25

    @display(
        description=_("Статус"),
        label={True: "success", False: "danger"},
    )
    def processed_badge(self, obj):
        return obj.is_processed

    fieldsets = (
        (None, {
            "fields": (
                ("name", "company"),
                ("email", "phone"),
                "message",
                ("is_processed", "created_at"),
            ),
        }),
    )

    @admin.action(description=_("Пометить обработанными"))
    def mark_processed(self, request, queryset):
        updated = queryset.filter(is_processed=False).update(is_processed=True)
        self.message_user(request, _("%(count)d обработано.") % {"count": updated})


# ────────────────────────────────────────────
# Messages
# ────────────────────────────────────────────

@admin.register(Message)
class MessageAdmin(ModelAdmin):
    list_display = ("id", "sender", "deal", "short_text", "timestamp")
    list_filter = ("timestamp",)
    search_fields = ("text", "sender__email", "deal__title")
    autocomplete_fields = ["deal", "sender"]
    readonly_fields = ("timestamp",)
    list_per_page = 30

    fieldsets = (
        (None, {
            "fields": (
                ("deal", "sender"),
                "text",
                "timestamp",
            ),
        }),
    )

    @display(description=_("Текст"))
    def short_text(self, obj):
        return obj.text[:80] + "..." if len(obj.text) > 80 else obj.text


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
        (None, {
            "fields": (
                ("action", "level"),
                "detail",
                ("user", "timestamp"),
            ),
        }),
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
        "quote_item", "changed_by", "frozen_base_price",
        "margin_percent", "final_price_excl_vat", "quantity", "created_at"
    )
    list_filter = ("created_at",)
    search_fields = ("quote_item__product__name", "changed_by__email", "change_reason")
    readonly_fields = (
        "quote_item", "changed_by", "frozen_base_price",
        "logistics_cost", "customs_duty", "margin_percent",
        "landed_cost", "final_price_excl_vat", "quantity",
        "change_reason", "created_at",
    )
    list_per_page = 30

    fieldsets = (
        (None, {
            "fields": (
                ("quote_item", "changed_by"),
                ("change_reason", "created_at"),
            ),
        }),
        (_("Финансовый снимок"), {
            "classes": ["tab"],
            "fields": (
                ("frozen_base_price", "logistics_cost", "customs_duty"),
                ("margin_percent", "landed_cost", "final_price_excl_vat"),
                "quantity",
            ),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
