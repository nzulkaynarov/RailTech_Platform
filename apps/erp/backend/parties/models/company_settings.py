"""CompanySettings — машинные настройки компании (payment_terms_days и т.п.)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CompanySettings(models.Model):
    """Per-company КП defaults + the document-numbering scheme.

    The selling company sets these once (OWNER-gated). New КП built by the company
    pre-fill from `default_*` so the seller team isn't re-entering the same Incoterm,
    valuta, ставку НДС, маржу and validity on every offer. `doc_number_prefix` brands
    the company's own document numbering (contracts/invoices/acts): with prefix "ACME"
    a contract reads `ACME-CT-2026-00001`; without it the platform default `CT-2026-00001`.
    One settings row per company (get-or-create via the `Company.settings` accessor).
    """

    company = models.OneToOneField(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="settings_rel",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относятся настройки"),
    )

    # ── КП defaults (inherited by a new Quote on CREATE only) ──────────────────
    default_delivery_basis = models.ForeignKey(
        "core.DeliveryBasis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Базис поставки по умолчанию"),
        help_text=_("Incoterm, подставляемый в новый КП (FCA, CIP, DDP …)"),
    )
    default_cost_currency = models.ForeignKey(
        "core.Currency",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта себестоимости по умолчанию"),
        help_text=_("Валюта базовой цены, наследуемая новыми позициями КП"),
    )
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Ставка НДС по умолчанию (%)"),
        help_text=_("Ставка НДС, подставляемая в новый КП"),
    )
    default_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Маржа по умолчанию (%)"),
        help_text=_("Наценка на себестоимость, подставляемая в новый КП"),
    )
    default_offer_validity_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок действия КП по умолчанию (дней)"),
        help_text=_("Через сколько дней истекает новый КП (valid_until = сегодня + N)"),
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок оплаты счёта (дней)"),
        help_text=_(
            "Через сколько дней после ВЫСТАВЛЕНИЯ счёт должен быть оплачен. "
            "Пусто — платформенное умолчание. От этого срока считается напоминание об оплате."
        ),
    )
    default_payment_terms = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Условия оплаты по умолчанию"),
        help_text=_("Напр. «100% предоплата» — подставляется в блок «Условия поставки» КП"),
    )
    default_warranty_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Гарантия по умолчанию (мес.)"),
        help_text=_("Срок гарантии в месяцах для блока «Условия поставки» КП"),
    )
    min_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=15,
        verbose_name=_("Порог маржи (%)"),
        help_text=_("Минимальная валовая маржа (на цене). Ниже — КП требует согласования."),
    )
    target_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25,
        verbose_name=_("Целевая маржа (%)"),
        help_text=_("Желаемая валовая маржа (на цене) — зелёная зона в конструкторе КП."),
    )

    # ── Document numbering scheme ──────────────────────────────────────────────
    doc_number_prefix = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("Префикс нумерации документов"),
        help_text=_("Префикс номеров документов компании (напр. «ACME» → ACME-CT-2026-00001)"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Настройки компании")
        verbose_name_plural = _("Настройки компаний")

    def __str__(self):
        return f"Настройки: {self.company.name}"
