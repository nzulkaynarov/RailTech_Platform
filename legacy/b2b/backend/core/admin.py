from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from core.admin_mixins import ReadOnlyInspectionMixin
from core.models import SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """
    Read-only inspection of SystemSetting singleton.
    Business users edit via React Admin /admin/settings.
    Engineers can inspect current values and pghistory audit trail here.
    """

    list_display = ("__str__", "vat_rate", "standard_margin", "maintenance_mode", "updated_at")

    fieldsets = (
        (
            _("Финансы"),
            {
                "fields": ("vat_rate", "standard_margin", "exchange_rate_usd_uzs"),
            },
        ),
        (
            _("Платформа"),
            {
                "classes": ["tab"],
                "fields": ("platform_name", "maintenance_mode"),
            },
        ),
        (
            _("Безопасность"),
            {
                "classes": ["tab"],
                "fields": ("is_two_factor_required",),
            },
        ),
        (
            _("Системное"),
            {
                "classes": ["tab"],
                "fields": ("updated_at",),
            },
        ),
    )
