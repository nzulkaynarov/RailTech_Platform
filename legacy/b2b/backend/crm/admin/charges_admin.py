"""Unfold admin for КП charge types and per-Incoterm charge templates.

Owner-facing config: edit the charge-type catalogue and the basis → default-charges
templates that auto-populate a КП when its delivery basis is selected.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin

from crm.models import ChargeTemplate, ChargeType


@admin.register(ChargeType)
class ChargeTypeAdmin(ModelAdmin):
    list_display = ("code", "name", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("code", "name")
    ordering = ("sort_order", "name")


@admin.register(ChargeTemplate)
class ChargeTemplateAdmin(ModelAdmin):
    list_display = (
        "delivery_basis",
        "charge_type",
        "default_amount",
        "default_rate_percent",
        "is_deduction",
        "sort_order",
        "is_active",
    )
    list_filter = ("delivery_basis", "is_deduction", "is_active")
    list_editable = ("default_amount", "default_rate_percent", "is_deduction", "sort_order", "is_active")
    list_select_related = ("delivery_basis", "charge_type")
    ordering = ("delivery_basis", "sort_order")
