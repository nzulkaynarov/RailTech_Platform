from django.db import models
from django.utils.translation import gettext_lazy as _

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


class SupplierSubscription(models.Model):
    """
    Подписка поставщика на платформу.
    Тарифы до конца календарного года + ежемесячная оплата.
    """

    PLAN_CHOICES = [
        ("BASIC", _("Базовый")),
        ("STANDARD", _("Стандартный")),
        ("PREMIUM", _("Премиум")),
    ]
    STATUS_CHOICES = [
        ("TRIAL", _("Пробный период")),
        ("ACTIVE", _("Активна")),
        ("PAST_DUE", _("Просрочена")),
        ("SUSPENDED", _("Приостановлена")),
        ("CANCELLED", _("Отменена")),
    ]

    company = models.OneToOneField(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="subscription",
        verbose_name=_("Компания"),
        help_text=_("Компания-поставщик (одна подписка на компанию)"),
    )
    plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default="BASIC",
        verbose_name=_("Тарифный план"),
        help_text=_("Базовый, Стандартный или Премиум"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="TRIAL",
        verbose_name=_("Статус"),
        help_text=_("Текущее состояние подписки"),
    )

    # Billing
    monthly_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Ежемесячная стоимость"),
        help_text=_("Сумма ежемесячного платежа"),
    )
    currency = models.ForeignKey(
        "master_data.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта"),
        help_text=_("Валюта расчётов"),
    )
    valid_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует с"),
        help_text=_("Дата начала действия подписки"),
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания (обычно конец календарного года)"),
    )
    last_payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Последний платёж"),
        help_text=_("Дата последнего успешного платежа"),
    )
    next_payment_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Следующий платёж"),
        help_text=_("Дата ожидаемого следующего платежа"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки"),
        help_text=_("Внутренние заметки администратора"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Подписка поставщика")
        verbose_name_plural = _("Подписки поставщиков")

    def __str__(self):
        return f"{self.company.name} — {self.get_plan_display()} ({self.get_status_display()})"

    @property
    def is_active(self):
        from django.utils import timezone

        today = timezone.now().date()
        return self.status == "ACTIVE" and self.valid_until and self.valid_until >= today

    @property
    def is_operational(self) -> bool:
        """Subscription permits supplier operations (ACTIVE or TRIAL within validity)."""
        from django.utils import timezone

        today = timezone.now().date()
        if self.status not in ("ACTIVE", "TRIAL"):
            return False
        if self.valid_until and self.valid_until < today:
            return False
        return True
