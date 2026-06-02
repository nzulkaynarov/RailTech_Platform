from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import Currency

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# RFQ / Supplier bidding
# ────────────────────────────────────────────


class SupplierBid(models.Model):
    """Предложение поставщика по открытому RFQ."""

    STATUS_CHOICES = [
        ("DRAFT", _("Черновик")),
        ("SUBMITTED", _("Подано")),
        ("ACCEPTED", _("Принято")),
        ("REJECTED", _("Отклонено")),
        ("WITHDRAWN", _("Отозвано")),
    ]

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.CASCADE,
        related_name="supplier_bids",
        verbose_name=_("Сделка / RFQ"),
    )
    supplier = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="supplier_bids",
        verbose_name=_("Поставщик"),
    )
    submitted_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default="DRAFT",
        db_index=True,
    )
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Предложение поставщика")
        verbose_name_plural = _("Предложения поставщиков")
        unique_together = [("deal", "supplier")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Bid {self.supplier_id} → deal {self.deal_id} ({self.status})"


class SupplierBidItem(models.Model):
    """Позиция в SupplierBid — одна за QuoteItem / спецификация."""

    bid = models.ForeignKey(
        "crm.SupplierBid",
        on_delete=models.CASCADE,
        related_name="items",
    )
    quote_item = models.ForeignKey(
        "crm.QuoteItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("Позиция bid'а")
        verbose_name_plural = _("Позиции bid'ов")

    def __str__(self):
        return f"{self.description} x{self.quantity} @ {self.unit_price}"
