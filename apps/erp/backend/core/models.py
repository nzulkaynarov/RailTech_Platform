"""
Core models — platform-level singletons and configuration.

SystemSetting: single-row table holding global business parameters
(VAT, margins, platform name, feature flags). Edited via React Admin,
inspected via Unfold. Tracked by pghistory for audit trail.
"""

from decimal import Decimal

import pghistory
import pgtrigger
from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _

SYSTEM_SETTING_CACHE_KEY = "core:system_setting"
SYSTEM_SETTING_CACHE_TTL = 300  # 5 minutes


@pghistory.track(
    pghistory.RowEvent("system_setting.snapshot", row=pghistory.New, operation=pgtrigger.Update),
)
class SystemSetting(models.Model):
    """
    Singleton table for platform-wide business parameters.

    There should be exactly ONE row. Use `SystemSetting.load()` to get it
    (creates a default row if none exists). Never create rows manually.
    """

    # ─── Finance ────────────────────────────────────────────────────────
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("12.00"),
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Процент НДС, применяемый к котировкам"),
    )
    standard_margin = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        verbose_name=_("Стандартная маржа (%)"),
        help_text=_("Маржа по умолчанию для новых позиций КП"),
    )
    exchange_rate_usd_uzs = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("12500.00"),
        verbose_name=_("Курс USD/UZS"),
        help_text=_("Справочный курс (может обновляться автоматически)"),
    )

    # ─── Platform ───────────────────────────────────────────────────────
    platform_name = models.CharField(
        max_length=200,
        default="RailTech B2B Ecosystem",
        verbose_name=_("Название платформы"),
    )
    maintenance_mode = models.BooleanField(
        default=False,
        verbose_name=_("Режим обслуживания"),
        help_text=_("Когда включён — пользователи видят заглушку"),
    )

    # ─── Security ───────────────────────────────────────────────────────
    is_two_factor_required = models.BooleanField(
        default=False,
        verbose_name=_("Обязательная 2FA"),
        help_text=_("Требовать двухфакторную аутентификацию для всех пользователей"),
    )

    # ─── Meta ───────────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлено"))

    class Meta:
        verbose_name = _("Системные настройки")
        verbose_name_plural = _("Системные настройки")

    def __str__(self):
        return f"SystemSetting (VAT={self.vat_rate}%, margin={self.standard_margin}%)"

    def save(self, *args, **kwargs):
        # Enforce singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SYSTEM_SETTING_CACHE_KEY)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton
        pass

    @classmethod
    def load(cls) -> "SystemSetting":
        """
        Load the singleton SystemSetting. Creates a default row if none exists.
        Cached for SYSTEM_SETTING_CACHE_TTL seconds.
        """
        obj = cache.get(SYSTEM_SETTING_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SYSTEM_SETTING_CACHE_KEY, obj, SYSTEM_SETTING_CACHE_TTL)
        return obj
