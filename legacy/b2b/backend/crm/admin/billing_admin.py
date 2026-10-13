from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from core.admin_mixins import ReadOnlyInspectionMixin

from ..models import Act, Contract, Fulfillment, Invoice, Payment

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────
from .inlines import InvoiceItemInline, PaymentInline


class _ServiceMintedDocAdminMixin:
    """Block raw Unfold ADD even for a superuser (audit H3).

    Contract/Invoice/Act/Payment MUST be created through their services, which mint the
    sequential `number` (Contract/Invoice/Act), render the PDF, write ActivityLog and recompute
    invoice.amount_paid (Payment). A hand-created row in Unfold would save an EMPTY unique
    `number` (→ IntegrityError 500 on the second add) or leave invoice.amount_paid stale. The
    superuser keeps full change/delete via ReadOnlyInspectionMixin — only ADD is blocked here.
    Must precede ReadOnlyInspectionMixin in the MRO so this has_add_permission wins.
    """

    def has_add_permission(self, request):
        return False


@admin.register(Contract)
class ContractAdmin(_ServiceMintedDocAdminMixin, ReadOnlyInspectionMixin, ModelAdmin):
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
    list_select_related = ("deal", "deal__company", "status")

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
        # status is a FK lookup now (F5.4); its name drives the label map above.
        return obj.status.name if obj.status_id else "—"


@admin.register(Invoice)
class InvoiceAdmin(_ServiceMintedDocAdminMixin, ReadOnlyInspectionMixin, ModelAdmin):
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
    list_select_related = ("deal", "deal__company", "status")

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
        # status is a FK lookup now (F5.4); its name drives the label map above.
        return obj.status.name if obj.status_id else "—"


@admin.register(Payment)
class PaymentAdmin(_ServiceMintedDocAdminMixin, ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("invoice", "amount", "method", "paid_at", "reference", "recorded_by")
    list_filter = ("method", "paid_at")
    search_fields = ("invoice__number", "reference", "recorded_by__email")
    autocomplete_fields = ("invoice", "recorded_by")
    readonly_fields = ("recorded_by", "created_at", "proof_file")
    list_per_page = 25
    list_select_related = ("invoice", "recorded_by")


@admin.register(Act)
class ActAdmin(_ServiceMintedDocAdminMixin, ReadOnlyInspectionMixin, ModelAdmin):
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
    list_select_related = ("deal", "deal__company", "status")

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
        # status is a FK lookup now (F5.4); its name drives the label map above.
        return obj.status.name if obj.status_id else "—"


@admin.register(Fulfillment)
class FulfillmentAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("deal", "fulfillment_status", "expected_delivery_date", "tracking_number", "carrier", "updated_at")
    list_filter = ("status", "expected_delivery_date")
    list_filter_submit = True
    search_fields = ("deal__id", "tracking_number", "carrier", "deal__company__name")
    autocomplete_fields = ("deal", "contract")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    list_select_related = ("deal", "deal__company", "status")

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
        # status is a FK lookup now (F5.4) — its name drives the label map above.
        return obj.status.name if obj.status_id else "—"
