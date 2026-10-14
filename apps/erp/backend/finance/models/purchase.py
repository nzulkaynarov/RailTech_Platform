from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class DealPurchaseActual(models.Model):
    """Фактическая закупка по сделке в одной валюте себестоимости (M1-ERP-08).

    Из неё и снимка курса КП считается отклонение маржи (`finance.services.margin_deviation`); цена
    клиенту не пересчитывается (BUSINESS «Курс валюты»). До M4 вносится вручную (право `finance.rates`
    или `supply.manage`); с M4 те же цифры придут из счетов поставщиков.
    """

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="purchase_actuals",
        verbose_name=_("Сделка"),
    )
    currency = models.ForeignKey(
        "core.Currency",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Валюта закупки"),
        help_text=_("Валюта себестоимости строк КП, по которым закупка"),
    )
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Фактическая себестоимость в валюте"),
        help_text=_("Сколько фактически стоила закупка в этой валюте; пусто — как в КП (отклонение только по курсу)"),
    )
    rate_to_uzs = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(0)],
        verbose_name=_("Фактический курс к UZS"),
        help_text=_("Сколько сум за 1 единицу валюты по факту закупки (для UZS — 1)"),
    )
    purchased_on = models.DateField(verbose_name=_("Дата закупки"))
    note = models.CharField(max_length=500, blank=True, default="", verbose_name=_("Комментарий"))
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Внёс"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Изменено"))

    class Meta:
        verbose_name = _("Фактическая закупка по сделке")
        verbose_name_plural = _("Фактические закупки по сделкам")
        ordering = ["deal_id", "currency__code"]
        constraints = [
            models.UniqueConstraint(fields=["deal", "currency"], name="uniq_deal_purchase_actual_currency"),
        ]

    def __str__(self):
        return f"{self.deal_id}: {self.amount} {self.currency_id} @ {self.rate_to_uzs}"
