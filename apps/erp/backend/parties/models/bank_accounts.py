"""Банковские счета компании (решение владельца 2026-11-11): основной, дополнительные, валютные.

Эталоны — Odoo `res.partner.bank`, ERPNext Bank Account (`is_default`), 1С «Банковские счета организации»
(`docs/research/2026-11-11-documents-templates/README.md` §1): счета — список, у каждой валюты один основной; документ
берёт основной счёт своей валюты. Использованный в документах счёт не удаляют — отключают.
"""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class CompanyBankAccount(models.Model):
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="bank_accounts",
        verbose_name=_("Компания"),
    )
    # ISO 20022 (ADR-0029): страна банка решает формат номера (IBAN, 20 цифр Узбекистана, иной) и код банка в стране.
    bank_country = models.ForeignKey(
        "core.Country",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Страна банка"),
    )
    holder_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Владелец счёта"),
        help_text=_("Пусто — название компании"),
    )
    holder_name_latin = models.CharField(
        max_length=140, blank=True, default="", verbose_name=_("Владелец счёта латиницей"), help_text=_("Для SWIFT")
    )
    bank_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Банк"))
    bank_address = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Адрес банка"))
    mfo = models.CharField(
        max_length=15,
        blank=True,
        default="",
        verbose_name=_("Код банка в стране"),
        help_text=_("МФО для Узбекистана; Bankleitzahl, sort code, ABA — для других стран"),
    )
    account = models.CharField(max_length=50, verbose_name=_("Номер счёта"), help_text=_("IBAN или номер счёта"))
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT, related_name="+", verbose_name=_("Валюта"))
    swift = models.CharField(max_length=11, blank=True, default="", verbose_name=_("SWIFT"))
    intermediary_swift = models.CharField(
        max_length=11, blank=True, default="", verbose_name=_("SWIFT банка-посредника")
    )
    intermediary_account = models.CharField(
        max_length=50, blank=True, default="", verbose_name=_("Счёт банка получателя у посредника")
    )
    # Прежний свободный текст; в форму не входит (ADR-0029 п. 1), остаётся для чтения старых записей.
    correspondent_bank = models.TextField(blank=True, default="", verbose_name=_("Банк-корреспондент (текст)"))
    is_default = models.BooleanField(default=False, verbose_name=_("Основной для валюты"))
    is_active = models.BooleanField(default=True, verbose_name=_("Действует"))
    order = models.PositiveIntegerField(default=0, verbose_name=_("Порядок"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Банковский счёт компании")
        verbose_name_plural = _("Банковские счета компании")
        ordering = ["company_id", "-is_default", "order", "id"]
        constraints = [
            # Один основной счёт на валюту у компании.
            models.UniqueConstraint(
                fields=["company", "currency"],
                condition=Q(is_default=True),
                name="uq_company_bank_account_default_per_currency",
            ),
            models.UniqueConstraint(fields=["company", "account"], name="uq_company_bank_account_number"),
        ]

    def __str__(self):
        return f"{self.account} ({self.currency_id})"

    def as_text(self) -> str:
        """Реквизиты одной строкой — снимок в выпущенном счёте: набор полей по стране банка (ADR-0029 п. 5)."""
        from parties.banking import print_rows

        return ", ".join(f"{label}: {value}" for label, value in print_rows(self, with_party=False))
