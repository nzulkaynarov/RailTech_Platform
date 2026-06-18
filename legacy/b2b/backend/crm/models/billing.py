from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import act_pdf_path, get_private_storage, invoice_pdf_path, payment_proof_path
from master_data.models import Currency

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


class Invoice(models.Model):
    """Инвойс на оплату по контракту."""

    STATUS_CHOICES = [
        ("DRAFT", _("Черновик")),
        ("ISSUED", _("Выставлен")),
        ("PARTIAL", _("Частично оплачен")),
        ("PAID", _("Оплачен")),
        ("OVERDUE", _("Просрочен")),
        ("CANCELLED", _("Отменён")),
    ]

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.CASCADE,
        related_name="invoices",
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        "crm.Contract",
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
        verbose_name=_("Контракт"),
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер инвойса"))
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="DRAFT",
        db_index=True,
        verbose_name=_("Статус"),
    )
    issued_at = models.DateField(null=True, blank=True, verbose_name=_("Дата выставления"))
    due_date = models.DateField(null=True, blank=True, verbose_name=_("Срок оплаты"))

    subtotal_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_incl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    pdf_file = models.FileField(
        upload_to=invoice_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Инвойс")
        verbose_name_plural = _("Инвойсы")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invoice {self.number}"

    @property
    def balance_due(self) -> Decimal:
        return Decimal(self.total_incl_vat) - Decimal(self.amount_paid or 0)


class InvoiceItem(models.Model):
    """Позиция инвойса (копия QuoteItem на момент выставления)."""

    invoice = models.ForeignKey(
        "crm.Invoice",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Инвойс"),
    )
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_quote_item = models.ForeignKey(
        "crm.QuoteItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Позиция инвойса")
        verbose_name_plural = _("Позиции инвойсов")

    def __str__(self):
        return f"{self.description} x{self.quantity}"


class Payment(models.Model):
    """Платёж по инвойсу."""

    METHOD_CHOICES = [
        ("BANK_TRANSFER", _("Банковский перевод")),
        ("CARD", _("Банковская карта")),
        ("CASH", _("Наличные")),
        ("OTHER", _("Другое")),
    ]

    invoice = models.ForeignKey(
        "crm.Invoice",
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name=_("Инвойс"),
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default="BANK_TRANSFER")
    paid_at = models.DateField(verbose_name=_("Дата платежа"))
    reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Референс / номер операции"),
    )
    proof_file = models.FileField(
        upload_to=payment_proof_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Подтверждение"),
    )
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Платёж")
        verbose_name_plural = _("Платежи")
        ordering = ["-paid_at"]
        constraints = [
            # A bank reference uniquely identifies a real-world payment. Enforce
            # at the DB level so a double-submit with the same reference cannot
            # double-count amount_paid, even on a code path that skips the
            # service-layer check. Blank references are allowed to repeat.
            models.UniqueConstraint(
                fields=["invoice", "reference"],
                condition=~models.Q(reference=""),
                name="uniq_payment_invoice_reference",
            ),
        ]

    def __str__(self):
        return f"Payment {self.amount} on {self.paid_at}"


class Act(models.Model):
    """Акт выполненных работ / приёма-передачи."""

    STATUS_CHOICES = [
        ("DRAFT", _("Черновик")),
        ("ISSUED", _("Выставлен")),
        ("SIGNED", _("Подписан")),
        ("CANCELLED", _("Отменён")),
    ]

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.CASCADE,
        related_name="acts",
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        "crm.Contract",
        on_delete=models.PROTECT,
        related_name="acts",
        null=True,
        blank=True,
    )
    invoice = models.ForeignKey(
        "crm.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acts",
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер акта"))
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="DRAFT",
        db_index=True,
    )
    issued_at = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    pdf_file = models.FileField(
        upload_to=act_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    signed_file = models.FileField(
        upload_to=act_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Акт")
        verbose_name_plural = _("Акты")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Act {self.number} ({self.status})"
