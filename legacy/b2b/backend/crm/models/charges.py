"""КП-level charges (UBL document AllowanceCharge) and per-Incoterm charge templates.

Kept as a self-contained module (split out of quotes.py) so the charge/template
feature is one isolated unit, not woven through the quote model file.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import DeliveryBasis


class QuoteCharge(models.Model):
    """
    Статья расхода уровня КП — UBL 2.1 document-level cac:AllowanceCharge.

    Добавляется на ВЕСЬ КП (не на позицию): фрахт, страховка, аренда, ЗП проектной
    команды, комиссионные, сертификация, штрафы и пр. Входит в базу до НДС:
      tax_exclusive = Σ(позиции) + Σ(charge − allowance)
    Поштучной аллокации по весу/объёму НЕТ — это задача спец-сервисов, не наша.
    Сумма вводится в валюте КП (quote_currency); конвертацию делает менеджер вручную.
    """

    quote = models.ForeignKey(
        "crm.Quote",
        on_delete=models.CASCADE,
        related_name="charges",
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому относится статья расхода"),
    )
    charge_type = models.ForeignKey(
        "crm.ChargeType",
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
    # UBL MultiplierFactorNumeric: процент от суммы позиций (база до НДС). Если задан —
    # имеет приоритет над amount (эффективная сумма = subtotal × rate_percent / 100).
    # Поддерживает «−5% на весь КП» и симметрично «+N% начисление».
    rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Процент (%)"),
        help_text=_("Процент от суммы позиций. Если задан — приоритетнее фиксированной суммы"),
    )
    # UBL ChargeIndicator: False = начисление (+, расход), True = скидка/уценка (−).
    is_deduction = models.BooleanField(
        default=False,
        verbose_name=_("Скидка (вычет)"),
        help_text=_("Если включено — сумма вычитается из базы до НДС (UBL allowance)"),
    )
    # Set when the row was auto-created from a ChargeTemplate (vs added by hand) —
    # lets the seller tell template defaults from manual additions.
    from_template = models.BooleanField(
        default=False,
        verbose_name=_("Из шаблона"),
        help_text=_("Строка создана автоматически из шаблона базиса поставки"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
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
        ordering = ["id"]

    def resolve_signed(self, subtotal):
        """
        Эффективная сумма со знаком для агрегации в базу до НДС.
        rate_percent (если задан) считается от subtotal (суммы позиций), иначе amount.
        Расход даёт (+), скидка (is_deduction) — (−).
        """
        if self.rate_percent is not None:
            base = subtotal * (self.rate_percent / Decimal("100"))
        else:
            base = self.amount
        return -base if self.is_deduction else base

    def __str__(self):
        sign = "−" if self.is_deduction else "+"
        value = f"{self.rate_percent}%" if self.rate_percent is not None else self.amount
        return f"{self.charge_type} {sign}{value} (КП #{self.quote_id})"

    def save(self, *args, **kwargs):
        """После изменения статьи пересчитываем агрегаты КП (если не отложено)."""
        skip_recalculate = kwargs.pop("skip_recalculate", False)
        super().save(*args, **kwargs)
        if not skip_recalculate:
            self.quote.recalculate_totals()


class ChargeTemplate(models.Model):
    """
    Шаблон статей расхода для базиса поставки (Incoterm cost profile).

    Овнер настраивает в админке: к каждому базису — набор статей по умолчанию. При
    выборе базиса на КП эти статьи авто-создаются как QuoteCharge (from_template=True),
    после чего продавец правит их вручную. Глобальные (одни на платформу) — для
    единственного продавца RailTech; при необходимости позже заскоупим на компанию.
    """

    delivery_basis = models.ForeignKey(
        DeliveryBasis,
        on_delete=models.CASCADE,
        related_name="charge_templates",
        verbose_name=_("Базис поставки"),
        help_text=_("Incoterm, к которому привязан шаблон статей"),
    )
    charge_type = models.ForeignKey(
        "crm.ChargeType",
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
        ordering = ["delivery_basis", "sort_order", "id"]
        # One row per (basis, charge type) — the template is the set of types for a basis.
        unique_together = [("delivery_basis", "charge_type")]

    def __str__(self):
        return f"{self.delivery_basis.code}: {self.charge_type}"
