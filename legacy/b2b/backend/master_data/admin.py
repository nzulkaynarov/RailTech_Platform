from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Country, Currency, UnitOfMeasure, DeliveryBasis


@admin.register(Country)
class CountryAdmin(ModelAdmin):
    list_display = ['name', 'code', 'alpha2', 'vat_rate', 'sort_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code', 'alpha2']
    list_editable = ['sort_order', 'is_active']


@admin.register(Currency)
class CurrencyAdmin(ModelAdmin):
    list_display = ['name', 'code', 'symbol', 'sort_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    list_editable = ['sort_order', 'is_active']


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(ModelAdmin):
    list_display = ['name', 'code', 'sort_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    list_editable = ['sort_order', 'is_active']


@admin.register(DeliveryBasis)
class DeliveryBasisAdmin(ModelAdmin):
    list_display = ['name', 'code', 'sort_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    list_editable = ['sort_order', 'is_active']
