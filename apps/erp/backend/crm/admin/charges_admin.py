"""Unfold admin for the КП charge-type lookup.

ChargeType is a master-data lookup → stays in Unfold (engineer plane). The per-company
charge TEMPLATES are business config owned by the Company Admin, so they live in the
React org-admin zone (/crm/charge-templates/ + Settings → Templates), NOT here — ADR-0003.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin

from crm.models import ChargeType


@admin.register(ChargeType)
class ChargeTypeAdmin(ModelAdmin):
    list_display = ("code", "name", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("code", "name")
    ordering = ("sort_order", "name")
