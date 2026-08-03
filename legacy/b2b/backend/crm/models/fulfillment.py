from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import fulfillment_pdf_path, get_private_storage

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
    # D2b (Odoo Delivery Slip): отгрузка остаётся статусной лентой, печатается её НАКЛАДНАЯ.
    #
    # Номер берётся из ОБЩЕЙ схемы нумерации при первой печати и дальше не меняется. Раньше он
    # собирался как `DN-{id}` в пяти местах кода — мимо схемы, по которой идут все остальные
    # документы (квитанция уже по схеме: `RCP-2026-00001`). Эталон: Odoo даёт `stock.picking`
    # имя из последовательности (`WH/OUT/00001`), у SAP delivery note — собственный номерной
    # диапазон. Пустое поле = накладная ещё не печаталась; у СТАРЫХ отгрузок печатается прежний
    # `DN-{id}`, потому что этот номер уже на руках у контрагента (правило E3 «выпущенный
    # документ не переписывается»).
    note_number = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Номер накладной"))
    pdf_file = models.FileField(upload_to=fulfillment_pdf_path, storage=get_private_storage, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Исполнение сделки")
        verbose_name_plural = _("Исполнение сделок")

    def __str__(self):
        code = self.status.code if self.status_id else "—"
        return f"Fulfillment #{self.deal_id} ({code})"
