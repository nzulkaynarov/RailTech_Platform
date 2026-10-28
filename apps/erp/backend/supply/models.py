"""Закупки (D2-2, SPEC-v3 §7.4 «Склад», integration-map ERP-14): заказы поставщикам (ЗП-ГГГГ-NNN), приёмка, запросы цен.

Заказ поставщику идёт по статусам черновик → отправлен → подтверждён → получен (плюс «отменён»); переход — только
допустимый и под блокировкой строки заказа (`supply.services.orders`), недопустимый — 409. Приёмка частичная: строка
заказа копит `received_quantity`, заказ становится «получен», когда получены все строки. Цены поставщика (`unit_price`)
режутся правилами `supplier_prices` / `quote.view_cost_margin` (`inventory.access.can_see_supplier_prices`).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class OrderStatus(models.TextChoices):
    DRAFT = "draft", _("Черновик")
    SENT = "sent", _("Отправлен")
    CONFIRMED = "confirmed", _("Подтверждён")
    RECEIVED = "received", _("Получен")
    CANCELLED = "cancelled", _("Отменён")


#: Допустимые переходы статусов ЗП (SPEC-v3 §7.4); любой другой — 409 `TRANSITION_NOT_ALLOWED`.
TRANSITIONS = {
    OrderStatus.DRAFT: (OrderStatus.SENT, OrderStatus.CANCELLED),
    OrderStatus.SENT: (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    OrderStatus.CONFIRMED: (OrderStatus.RECEIVED, OrderStatus.CANCELLED),
    OrderStatus.RECEIVED: (),
    OrderStatus.CANCELLED: (),
}


class SupplierOrder(models.Model):
    number = models.CharField(max_length=32, unique=True, verbose_name=_("Номер ЗП"))
    number_year = models.PositiveIntegerField(editable=False)
    number_seq = models.PositiveIntegerField(editable=False)
    supplier = models.ForeignKey(
        "parties.Company", on_delete=models.PROTECT, related_name="supplier_orders", verbose_name=_("Поставщик")
    )
    status = models.CharField(max_length=10, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True)
    expected_date = models.DateField(null=True, blank=True, db_index=True, verbose_name=_("Ожидаемая дата"))
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.TextField(blank=True, default="", verbose_name=_("Примечание"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_to = models.EmailField(blank=True, default="", verbose_name=_("Отправлен на адрес"))
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancel_reason = models.CharField(max_length=500, blank=True, default="")
    overdue_notified_at = models.DateTimeField(
        null=True, blank=True, help_text=_("Когда уведомили о просрочке: одно уведомление на заказ")
    )

    class Meta:
        verbose_name = _("Заказ поставщику")
        verbose_name_plural = _("Заказы поставщикам")
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["number_year", "number_seq"], name="uniq_supplier_order_number")]

    def __str__(self):
        return self.number


class SupplierOrderLine(models.Model):
    order = models.ForeignKey(SupplierOrder, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveIntegerField(default=1)
    product = models.ForeignKey(
        "catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_order_lines"
    )
    name = models.CharField(max_length=500)
    article = models.CharField(max_length=120, blank=True, default="")
    unit = models.CharField(max_length=32, blank=True, default="")
    quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name=_("Цена поставщика за единицу")
    )
    deal = models.ForeignKey(
        "sales.Deal",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supplier_order_lines",
        verbose_name=_("Под проект"),
    )
    quote_item = models.ForeignKey(
        "sales.QuoteItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_order_lines"
    )

    class Meta:
        verbose_name = _("Строка заказа поставщику")
        verbose_name_plural = _("Строки заказов поставщикам")
        ordering = ["order_id", "position", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="supplier_order_line_quantity_positive"),
            models.CheckConstraint(
                condition=Q(received_quantity__lte=models.F("quantity")), name="supplier_order_line_received_le"
            ),
        ]

    @property
    def left(self) -> int:
        return self.quantity - self.received_quantity


class GoodsReceipt(models.Model):
    """Приёмка от поставщика по строкам ЗП (частичная): увеличивает остаток склада."""

    order = models.ForeignKey(SupplierOrder, on_delete=models.PROTECT, related_name="receipts")
    supplier_doc = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Накладная поставщика"))
    note = models.CharField(max_length=500, blank=True, default="")
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Приёмка")
        verbose_name_plural = _("Приёмки")
        ordering = ["-received_at", "-id"]


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(SupplierOrderLine, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.PositiveIntegerField()
    warehouse = models.ForeignKey(
        "inventory.Warehouse", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cell = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        verbose_name = _("Строка приёмки")
        verbose_name_plural = _("Строки приёмки")
        ordering = ["receipt_id", "id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="goods_receipt_line_quantity_positive")]


class OrderLogKind(models.TextChoices):
    CREATED = "created", _("Создан")
    EDITED = "edited", _("Изменён")
    SENT = "sent", _("Отправлен")
    CONFIRMED = "confirmed", _("Подтверждён")
    RECEIPT = "receipt", _("Приёмка")
    RECEIVED = "received", _("Получен")
    CANCELLED = "cancelled", _("Отменён")
    OVERDUE = "overdue", _("Просрочен")


class SupplierOrderLog(models.Model):
    """Журнал заказа: любое изменение статуса и приёмка — запись с автором и временем (SPEC-v3 §11.2 п. 8)."""

    order = models.ForeignKey(SupplierOrder, on_delete=models.CASCADE, related_name="log")
    kind = models.CharField(max_length=12, choices=OrderLogKind.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    detail = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Запись журнала заказа")
        verbose_name_plural = _("Журнал заказов поставщикам")
        ordering = ["created_at", "id"]


class PriceRequestStatus(models.TextChoices):
    SENT = "sent", _("Отправлен")
    FAILED = "failed", _("Не отправлен")


class PriceRequest(models.Model):
    """Запрос цены у поставщика из расчёта: письмо и журнал — кто, когда, кому, по каким строкам. Ответ поставщика
    вносится вручную (цена — в строку расчёта, `answered_at` — отметка здесь)."""

    supplier = models.ForeignKey(
        "parties.Company", on_delete=models.PROTECT, related_name="price_requests", verbose_name=_("Поставщик")
    )
    deal = models.ForeignKey(
        "sales.Deal", null=True, blank=True, on_delete=models.SET_NULL, related_name="price_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    to_email = models.EmailField()
    subject = models.CharField(max_length=300)
    note = models.CharField(max_length=1000, blank=True, default="")
    status = models.CharField(max_length=8, choices=PriceRequestStatus.choices, db_index=True)
    error = models.CharField(max_length=500, blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    answer_note = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        verbose_name = _("Запрос цены поставщику")
        verbose_name_plural = _("Запросы цен поставщикам")
        ordering = ["-requested_at", "-id"]


class PriceRequestLine(models.Model):
    request = models.ForeignKey(PriceRequest, on_delete=models.CASCADE, related_name="lines")
    quote_item = models.ForeignKey(
        "sales.QuoteItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="price_request_lines"
    )
    name = models.CharField(max_length=500)
    article = models.CharField(max_length=120, blank=True, default="")
    quantity = models.PositiveIntegerField()
    unit = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        ordering = ["request_id", "id"]
