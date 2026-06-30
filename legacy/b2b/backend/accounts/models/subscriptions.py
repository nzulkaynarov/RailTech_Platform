import pghistory
from django.db import models
from django.utils.translation import gettext_lazy as _

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


@pghistory.track()  # G6: audit engineer (Unfold superuser) edits to the seller billing gate
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


@pghistory.track()  # audit billing/admin grants & revocations of paid features
class CompanyEntitlement(models.Model):
    """Feature-keyed access grant — the monetization keystone (ADR-0006 §3).

    The app gates on a stable FEATURE_KEY (e.g. ``kp.send``, ``ai.draft``), NEVER a plan name —
    a company's plan / promo / demo state is projected into entitlement rows, so pricing and
    packaging changes never touch business code. Layered OVER SupplierSubscription: a feature is
    granted by an explicit row here (or by the always-free floor); the subscription remains the
    coarse "may this seller operate at all" gate. Feature-flags (global on/off) are separate.
    """

    ACCESS_CHOICES = [
        ("ENABLED", _("Включено")),
        ("DISABLED", _("Выключено")),
        ("DEMO", _("Демо")),  # feature usable but output is watermarked / send+export gated
    ]

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="entitlements",
        verbose_name=_("Компания"),
    )
    feature_key = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("Ключ функции"),
        help_text=_("Стабильный код функции (accounts.constants.FeatureKey), напр. kp.send"),
    )
    access = models.CharField(max_length=16, choices=ACCESS_CHOICES, default="ENABLED", verbose_name=_("Доступ"))
    limit = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Лимит"), help_text=_("Потолок использования (пусто — без лимита)")
    )
    credits = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Кредиты"), help_text=_("Расходуемый баланс (пусто — неприменимо)")
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Действует до"))
    note = models.CharField(max_length=255, blank=True, verbose_name=_("Заметка"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Право доступа компании")
        verbose_name_plural = _("Права доступа компаний")
        constraints = [
            models.UniqueConstraint(fields=["company", "feature_key"], name="uniq_company_feature_entitlement"),
        ]

    def __str__(self):
        return f"{self.company_id} · {self.feature_key} · {self.access}"

    def is_currently_granted(self) -> bool:
        """The feature is usable right now: not DISABLED, not expired, and (if credit-metered) has
        a positive balance. DEMO counts as usable — the watermark/send-gate is enforced at the
        feature's own call site via `entitlement_state`, not here."""
        from django.utils import timezone

        if self.access == "DISABLED":
            return False
        if self.expires_at is not None and self.expires_at < timezone.now():
            return False
        if self.credits is not None and self.credits <= 0:
            return False
        return True
