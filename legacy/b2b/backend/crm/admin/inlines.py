from unfold.admin import TabularInline

from ..models import InvoiceItem, Payment, Quote, QuoteItem

# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────


class QuoteItemInline(TabularInline):
    # ADR-0002 / Rule 8: oversight-only. A platform engineer must NOT author or re-price a
    # company's КП lines from Unfold — all line writes go through React Admin + crm.services.
    # Read-only inspection only; no add / change / delete.
    model = QuoteItem
    extra = 0
    tab = True
    can_delete = False
    show_change_link = False
    fields = [
        "product",
        "imported_raw_name",
        "quantity",
        "frozen_base_price",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "landed_cost",
        "final_price_excl_vat",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class QuoteInline(TabularInline):
    model = Quote
    extra = 0
    tab = True
    show_change_link = True
    fields = ["version", "status", "total_incl_vat", "created_at"]
    readonly_fields = ["version", "status", "total_incl_vat", "created_at"]


# ────────────────────────────────────────────
# Phase 2 models — read-only inspection (business writes go through React + services)
# See ADR-0001 + memory/tech_debt.
# ────────────────────────────────────────────


class InvoiceItemInline(TabularInline):
    model = InvoiceItem
    extra = 0
    can_delete = False
    show_change_link = False
    fields = ("description", "quantity", "unit_price_excl_vat", "line_total_excl_vat", "source_quote_item")
    readonly_fields = fields


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    fields = ("amount", "method", "paid_at", "reference", "recorded_by", "created_at")
    readonly_fields = fields
