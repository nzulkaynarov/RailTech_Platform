"""Строка расчёта (D2-1, SPEC-v3 §7.4; в docs/architecture/platform-bff.md §4 — «виза строки расчёта»).

Расчёт — черновик КП и его позиции (`QuoteItem`); здесь — то, чего у позиции КП нет: тип строки без карточки каталога,
вводные услуги (ставка бригады и дни — их заполняет гл. инженер) и виза строки по зоне. Зона строки — по типу позиции
(ADR-0012 п. 6): товар — `goods` (право `quote.visa_goods`), услуга — `services` (`quote.visa_services`). Виза
снимается любой правкой строки: она подтверждает именно эти цифры (паттерн «изменение документа сбрасывает
согласование», SAP B1 Approval Procedures). Новая версия КП строк расчёта не копирует — визы собираются заново.
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class CalcLineKind(models.TextChoices):
    """Тип строки без карточки каталога (у строки с карточкой тип берётся из каталога: услуга — `SERVICES`)."""

    GOODS = "goods", _("Товар")
    SERVICE = "service", _("Услуга")


class CalcLine(models.Model):
    item = models.OneToOneField(
        "sales.QuoteItem",
        on_delete=models.CASCADE,
        related_name="calc",
        verbose_name=_("Позиция КП"),
    )
    kind = models.CharField(
        max_length=8,
        choices=CalcLineKind.choices,
        default=CalcLineKind.GOODS,
        verbose_name=_("Тип строки"),
        help_text=_("Для строки без карточки каталога; у строки с карточкой тип задаёт каталог"),
    )
    crew_rate = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Ставка бригады, сум/день"),
    )
    crew_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Дней работы бригады"),
    )
    visa_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Визировал"),
    )
    visa_by_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Визировал (имя)"))
    visa_zone = models.CharField(max_length=16, blank=True, default="", verbose_name=_("Зона визы"))
    visa_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Время визы"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Строка расчёта")
        verbose_name_plural = _("Строки расчёта")

    def __str__(self):
        return f"Строка расчёта #{self.item_id}"
