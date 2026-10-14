"""КП-level charges (UBL document AllowanceCharge) and per-Incoterm charge templates."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import DeliveryBasis

from .lookups import ChargeType


class QuoteCharge(models.Model):
    """
    Статья расхода уровня КП — UBL 2.1 document-level cac:AllowanceCharge.
    """

    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        related_name="charges",
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому относится статья расхода"),
    )
    charge_type = models.ForeignKey(
        ChargeType,
        on_delete=models.PROTECT,
        related_name="quote_charges",
        verbose_name=_("Статья расхода"),
        help_text=_("Тип статьи из справочника (фрахт, аренда, комиссия …)"),
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Описание"),
        help_text=_("Уточнение статьи (напр. «аренда склада за июнь»)"),
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Сумма"),
        help_text=_("Фиксированная сумма в валюте КП (если rate_percent не задан)"),
    )
    rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Процент от суммы позиций (%)"),
        help_text=_("Если задан — сумма считается как процент от базы до НДС (приоритетнее суммы)"),
    )
    cost_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Себестоимость статьи для продавца"),
        help_text=_("Реальные затраты продавца по этой статье. Пусто = перевыставление без маржи (cost = amount)."),
    )
    is_deduction = models.BooleanField(
        default=False,
        verbose_name=_("Скидка (вычет)"),
        help_text=_("Если True — сумма вычитается из базы (скидка / бонус), а не добавляется"),
    )
    from_template = models.BooleanField(
        default=False,
        verbose_name=_("Создана из шаблона базиса"),
        help_text=_("True — строка авто-создана при выборе базиса поставки"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок в каскаде"),
        help_text=_("Позиция в каскаде: статья считается от нарастающего итога всех строк выше неё."),
    )
    resolved_base = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name=_("База (нарастающий итог до строки)")
    )
    resolved_amount = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name=_("Рассчитанная сумма (со знаком)")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Внёс"),
        help_text=_("Кто добавил статью расхода"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Дата обновления"))

    class Meta:
        verbose_name = _("Статья расхода КП")
        verbose_name_plural = _("Статьи расхода КП")
        ordering = ["sort_order", "id"]

    def resolve_signed(self, subtotal):
        if self.rate_percent is not None:
            base = subtotal * (self.rate_percent / Decimal("100"))
        else:
            base = self.amount
        return -base if self.is_deduction else base

    def resolve_seller_cost(self, subtotal):
        if self.is_deduction:
            return Decimal("0")
        if self.cost_amount is not None:
            return self.cost_amount
        if self.rate_percent is not None:
            return subtotal * (self.rate_percent / Decimal("100"))
        return self.amount

    def __str__(self):
        sign = "−" if self.is_deduction else "+"
        value = f"{self.rate_percent}%" if self.rate_percent is not None else self.amount
        return f"{self.charge_type} {sign}{value} (КП #{self.quote_id})"

    def save(self, *args, **kwargs):
        skip_recalculate = kwargs.pop("skip_recalculate", False)
        super().save(*args, **kwargs)
        if not skip_recalculate:
            self.quote.recalculate_totals()


class ChargeTemplate(models.Model):
    """
    Шаблон статей расхода для базиса поставки (Incoterm cost profile).
    """

    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="charge_templates",
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Компания"),
        help_text=_("Компания-владелец шаблона. Пусто = глобальный дефолт платформы."),
    )
    delivery_basis = models.ForeignKey(
        DeliveryBasis,
        on_delete=models.PROTECT,
        related_name="charge_templates",
        verbose_name=_("Базис поставки"),
        help_text=_("Incoterm, к которому привязан шаблон статей"),
    )
    charge_type = models.ForeignKey(
        ChargeType,
        on_delete=models.CASCADE,
        related_name="templates",
        verbose_name=_("Статья расхода"),
        help_text=_("Статья, добавляемая в КП по умолчанию для этого базиса"),
    )
    default_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Сумма по умолчанию"),
        help_text=_("Предзаполняемая сумма (если процент не задан)"),
    )
    default_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Процент по умолчанию (%)"),
        help_text=_("Предзаполняемый процент от суммы позиций (приоритетнее суммы)"),
    )
    is_deduction = models.BooleanField(
        default=False,
        verbose_name=_("Скидка (вычет)"),
        help_text=_("Шаблонная строка — скидка, а не расход"),
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_("Порядок"))
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))

    class Meta:
        verbose_name = _("Шаблон статьи расхода")
        verbose_name_plural = _("Справочник: Шаблоны статей расхода (по базисам)")
        ordering = ["company", "delivery_basis", "sort_order", "id"]
        unique_together = [("company", "delivery_basis", "charge_type")]

    def __str__(self):
        scope = self.company.name if self.company_id else "global"
        return f"[{scope}] {self.delivery_basis.code}: {self.charge_type}"
