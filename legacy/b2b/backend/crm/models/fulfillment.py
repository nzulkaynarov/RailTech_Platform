from django.db import models
from django.utils.translation import gettext_lazy as _

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


class Fulfillment(models.Model):
    """Исполнение сделки после подписания: отгрузка, доставка, приёмка."""

    deal = models.OneToOneField(
        "crm.Deal",
        on_delete=models.CASCADE,
        related_name="fulfillment",
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        "crm.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfillments",
    )
    status = models.ForeignKey(
        "crm.FulfillmentStatus",
        on_delete=models.PROTECT,
        related_name="fulfillments",
        null=True,
        db_index=True,
        verbose_name=_("Статус"),
    )
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    tracking_number = models.CharField(max_length=128, blank=True)
    carrier = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Исполнение сделки")
        verbose_name_plural = _("Исполнение сделок")

    def __str__(self):
        code = self.status.code if self.status_id else "—"
        return f"Fulfillment #{self.deal_id} ({code})"
