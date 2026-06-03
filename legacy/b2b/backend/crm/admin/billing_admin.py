from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from core.admin_mixins import ReadOnlyInspectionMixin

from ..models import Act, Contract, Fulfillment, Invoice, Payment, SupplierBid

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────
from .inlines import InvoiceItemInline, PaymentInline, SupplierBidItemInline


@admin.register(Contract)
class ContractAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("number", "deal", "contract_status", "total_amount", "created_at")
    list_filter = ("status", "created_at")
    list_filter_submit = True
    search_fields = ("number", "deal__id", "deal__company__name", "deal__company__inn")
    autocomplete_fields = ("deal", "quote", "currency", "client_signer", "manager_signer", "created_by")
    readonly_fields = (
        "number",
        "pdf_file",
        "signed_file",
        "client_signer",
        "client_signed_at",
        "manager_signer",
        "manager_signed_at",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_per_page = 25
    list_select_related = ("deal", "deal__company")

    @display(
        description=_("Статус"),
        label={
            "Черновик": "info",
            "Ожидает подписи клиента": "warning",
            "Ожидает подписи менеджера": "warning",
            "Подписан сторонами": "success",
            "Отменён": "danger",
        },
    )
    def contract_status(self, obj):
        return obj.get_status_display()


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("number", "deal", "invoice_status", "total_incl_vat", "amount_paid", "issued_at", "due_date")
    list_filter = ("status", "issued_at", "due_date")
    list_filter_submit = True
    search_fields = ("number", "deal__id", "deal__company__name", "deal__company__inn", "contract__number")
    autocomplete_fields = ("deal", "contract", "currency", "created_by")
    readonly_fields = (
        "number",
        "pdf_file",
        "amount_paid",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = [InvoiceItemInline, PaymentInline]
    list_per_page = 25
    list_select_related = ("deal", "deal__company")

    @display(
        description=_("Статус"),
        label={
            "Черновик": "info",
            "Выставлен": "warning",
            "Частично оплачен": "warning",
            "Оплачен": "success",
            "Просрочен": "danger",
            "Отменён": "danger",
        },
    )
    def invoice_status(self, obj):
        return obj.get_status_display()


@admin.register(Payment)
class PaymentAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("invoice", "amount", "method", "paid_at", "reference", "recorded_by")
    list_filter = ("method", "paid_at")
    search_fields = ("invoice__number", "reference", "recorded_by__email")
    autocomplete_fields = ("invoice", "recorded_by")
    readonly_fields = ("recorded_by", "created_at", "proof_file")
    list_per_page = 25
    list_select_related = ("invoice", "recorded_by")


@admin.register(Act)
class ActAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("number", "deal", "act_status", "total_amount", "issued_at", "signed_at")
    list_filter = ("status", "issued_at")
    list_filter_submit = True
    search_fields = ("number", "deal__id", "deal__company__name", "contract__number", "invoice__number")
    autocomplete_fields = ("deal", "contract", "invoice", "created_by")
    readonly_fields = (
        "number",
        "pdf_file",
        "signed_file",
        "signed_at",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_per_page = 25
    list_select_related = ("deal", "deal__company")

    @display(
        description=_("Статус"),
        label={
            "Черновик": "info",
            "Выставлен": "warning",
            "Подписан": "success",
            "Отменён": "danger",
        },
    )
    def act_status(self, obj):
        return obj.get_status_display()


@admin.register(Fulfillment)
class FulfillmentAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("deal", "fulfillment_status", "expected_delivery_date", "tracking_number", "carrier", "updated_at")
    list_filter = ("status", "expected_delivery_date")
    list_filter_submit = True
    search_fields = ("deal__id", "tracking_number", "carrier", "deal__company__name")
    autocomplete_fields = ("deal", "contract")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    list_select_related = ("deal", "deal__company")

    @display(
        description=_("Статус"),
        label={
            "Ожидает отгрузки": "info",
            "Отгружено": "warning",
            "В пути": "warning",
            "Доставлено": "warning",
            "Принято клиентом": "success",
            "Спорная ситуация": "danger",
        },
    )
    def fulfillment_status(self, obj):
        return obj.get_status_display()


@admin.register(SupplierBid)
class SupplierBidAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("deal", "supplier", "bid_status", "total_amount", "lead_time_days", "submitted_at")
    list_filter = ("status",)
    list_filter_submit = True
    search_fields = ("deal__id", "supplier__name", "supplier__inn")
    autocomplete_fields = ("deal", "supplier", "submitted_by", "currency")
    readonly_fields = ("submitted_at", "accepted_at", "created_at", "updated_at")
    inlines = [SupplierBidItemInline]
    list_per_page = 25
    list_select_related = ("deal", "supplier")

    @display(
        description=_("Статус"),
        label={
            "Черновик": "info",
            "Подано": "warning",
            "Принято": "success",
            "Отклонено": "danger",
            "Отозвано": "info",
        },
    )
    def bid_status(self, obj):
        return obj.get_status_display()
