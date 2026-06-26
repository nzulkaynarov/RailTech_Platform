from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Country, Currency, DeliveryBasis, ExchangeRate, UnitOfMeasure


@admin.register(Country)
class CountryAdmin(ModelAdmin):
    list_display = ["name", "code", "alpha2", "vat_rate", "sort_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code", "alpha2"]
    list_editable = ["sort_order", "is_active"]


@admin.register(Currency)
class CurrencyAdmin(ModelAdmin):
    list_display = ["name", "code", "symbol", "sort_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]
    list_editable = ["sort_order", "is_active"]


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]
    list_editable = ["sort_order", "is_active"]


@admin.register(DeliveryBasis)
class DeliveryBasisAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]
    list_editable = ["sort_order", "is_active"]


@admin.register(ExchangeRate)
class ExchangeRateAdmin(ModelAdmin):
    """Engineer view/insert of FX rates. Auto rows come from CBU (Celery beat); a manual
    row (source=MANUAL) lets an engineer pin a rate. NB: the КП-level override is separate
    (Quote.fx_manual) — this is the global market/manual rate, not a per-КП договорной курс.
    """

    list_display = ["currency", "rate_to_uzs", "rate_date", "source", "created_at"]
    list_filter = ["source", "currency", "rate_date"]
    search_fields = ["currency__code", "currency__name"]
    autocomplete_fields = ["currency"]
    date_hierarchy = "rate_date"
