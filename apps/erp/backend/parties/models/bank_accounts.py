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
    bank_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Банк"))
    mfo = models.CharField(max_length=10, blank=True, default="", verbose_name=_("МФО"))
    account = models.CharField(max_length=50, verbose_name=_("Расчётный счёт"))
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT, related_name="+", verbose_name=_("Валюта"))
    swift = models.CharField(max_length=11, blank=True, default="", verbose_name=_("SWIFT"))
    correspondent_bank = models.TextField(blank=True, default="", verbose_name=_("Банк-корреспондент"))
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
        """Строка реквизитов для печати: «р/с: …, МФО: …» (+ банк и SWIFT, если заданы)."""
        parts = [f"р/с: {self.account}"]
        if self.mfo:
            parts.append(f"МФО: {self.mfo}")
        if self.bank_name:
            parts.append(self.bank_name)
        if self.swift:
            parts.append(f"SWIFT: {self.swift}")
        return ", ".join(parts)
