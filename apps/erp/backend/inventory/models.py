"""Склад (D2-2, SPEC-v3 §7.4 «Склад», integration-map ERP-14): остатки, журнал движений, резервы, отгрузки.

Модель — паттерн Odoo Inventory / ERPNext Stock Ledger: остаток в ячейке ведётся вместе с журналом движений (каждое
изменение остатка — запись `StockMovement` в той же транзакции), «свободный» остаток = остаток − активные резервы
проектов («доступно к обещанию», ATP). Резерв привязан к строке расчёта (`QuoteItem`) проекта, поэтому «резерв под ЗВ/ПР» —
это резерв строк КП одной сделки. Все правки остатка идут под блокировкой строки товара (`select_for_update` на
`catalog.Product`): резерв, отгрузка и приёмка одного товара выстраиваются в очередь, гонка «двум проектам один остаток»
невозможна.

Количества — целые (как у `QuoteItem.quantity` и `DeliveryLine.quantity`). Цены поставщиков здесь не хранятся: они в
заказах поставщикам (`supply`), под правилами `supplier_prices` / `quote.view_cost_margin`.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Warehouse(models.Model):
    """Склад. Основной (`is_default`) заводится при первом обращении; ячейки — строкой в остатке (A-03-2)."""

    code = models.CharField(max_length=32, unique=True, verbose_name=_("Код"))
    name = models.CharField(max_length=120, verbose_name=_("Название"))
    is_default = models.BooleanField(default=False, verbose_name=_("Основной"))
    is_active = models.BooleanField(default=True, verbose_name=_("Действует"))

    class Meta:
        verbose_name = _("Склад")
        verbose_name_plural = _("Склады")
        ordering = ["-is_default", "code"]
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="uniq_default_warehouse")
        ]

    def __str__(self):
        return self.name


class StockBalance(models.Model):
    """Остаток товара в ячейке склада. Меняется только сервисом `inventory.services.stock` вместе с движением."""

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="stock_balances", verbose_name=_("Товар")
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="balances", verbose_name=_("Склад"))
    cell = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("Ячейка"), help_text=_("Пусто — без ячейки")
    )
    on_hand = models.PositiveIntegerField(default=0, verbose_name=_("Остаток"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Остаток")
        verbose_name_plural = _("Остатки")
        ordering = ["product_id", "warehouse_id", "cell"]
        constraints = [
            models.UniqueConstraint(fields=["product", "warehouse", "cell"], name="uniq_stock_balance_cell"),
        ]

    def __str__(self):
        return f"{self.product_id} · {self.cell or '—'}: {self.on_hand}"


class MovementKind(models.TextChoices):
    RECEIPT = "receipt", _("Приёмка от поставщика")
    SHIPMENT = "shipment", _("Отгрузка по проекту")
    ADJUSTMENT = "adjustment", _("Корректировка")


class StockMovement(models.Model):
    """Журнал движений: знаковое количество, источник (приёмка, отгрузка, корректировка) — мягкой ссылкой, чтобы
    `inventory` не зависел от `supply`."""

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="stock_movements", verbose_name=_("Товар")
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements")
    cell = models.CharField(max_length=32, blank=True, default="")
    quantity = models.IntegerField(verbose_name=_("Количество"), help_text=_("Плюс — приход, минус — расход"))
    kind = models.CharField(max_length=12, choices=MovementKind.choices, db_index=True)
    source_id = models.PositiveBigIntegerField(
        null=True, blank=True, verbose_name=_("Документ"), help_text=_("Приёмка или отгрузка, породившая движение")
    )
    note = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Движение по складу")
        verbose_name_plural = _("Движения по складу")
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=~Q(quantity=0), name="stock_movement_not_zero")]


class ReservationStatus(models.TextChoices):
    ACTIVE = "active", _("Действует")
    RELEASED = "released", _("Снят")
    FULFILLED = "fulfilled", _("Отгружен")


class Reservation(models.Model):
    """Резерв товара под строку расчёта проекта (заявки ЗВ / проекта ПР). Действует, пока не снят или не отгружен;
    резерв на строку один (`uniq_active_reservation_per_line`): повторное «Зарезервировать» меняет количество."""

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="reservations", verbose_name=_("Товар")
    )
    deal = models.ForeignKey(
        "sales.Deal", on_delete=models.PROTECT, related_name="stock_reservations", verbose_name=_("Заявка / проект")
    )
    quote_item = models.ForeignKey(
        "sales.QuoteItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_reservations",
        verbose_name=_("Строка расчёта"),
    )
    quantity = models.PositiveIntegerField(verbose_name=_("Зарезервировано"))
    shipped_quantity = models.PositiveIntegerField(default=0, verbose_name=_("Отгружено"))
    status = models.CharField(
        max_length=10, choices=ReservationStatus.choices, default=ReservationStatus.ACTIVE, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("Резерв")
        verbose_name_plural = _("Резервы")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="reservation_quantity_positive"),
            models.CheckConstraint(
                condition=Q(shipped_quantity__lte=models.F("quantity")), name="reservation_shipped_le"
            ),
            models.UniqueConstraint(
                fields=["quote_item"],
                condition=Q(status="active", quote_item__isnull=False),
                name="uniq_active_reservation_per_line",
            ),
        ]
        indexes = [models.Index(fields=["product", "status"], name="reservation_product_status_idx")]

    @property
    def remaining(self) -> int:
        """Сколько ещё удерживается за проектом (не отгружено)."""
        return self.quantity - self.shipped_quantity if self.status == ReservationStatus.ACTIVE else 0


class DocumentCounter(models.Model):
    """Счётчик NNN номеров складских документов по виду и году (ЗП-ГГГГ-NNN, ОТГ-ГГГГ-NNN): строка берётся под
    блокировкой, номер выдаётся без пропусков (как `sales.DealNumberCounter`)."""

    kind = models.CharField(max_length=8)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Счётчик номеров")
        verbose_name_plural = _("Счётчики номеров")
        constraints = [models.UniqueConstraint(fields=["kind", "year"], name="uniq_document_counter")]

    def __str__(self):
        return f"{self.kind} {self.year}: {self.last_value}"


class Shipment(models.Model):
    """Отгрузка по проекту со склада: строки, внутренняя накладная (номер ОТГ-ГГГГ-NNN), трек."""

    number = models.CharField(max_length=32, unique=True, verbose_name=_("Номер накладной"))
    number_year = models.PositiveIntegerField(editable=False)
    number_seq = models.PositiveIntegerField(editable=False)
    deal = models.ForeignKey(
        "sales.Deal", on_delete=models.PROTECT, related_name="stock_shipments", verbose_name=_("Заявка / проект")
    )
    tracking = models.CharField(max_length=128, blank=True, default="", verbose_name=_("Трек-номер"))
    carrier = models.CharField(max_length=128, blank=True, default="", verbose_name=_("Перевозчик"))
    note = models.CharField(max_length=500, blank=True, default="")
    shipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    shipped_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Отгрузка")
        verbose_name_plural = _("Отгрузки")
        ordering = ["-shipped_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["number_year", "number_seq"], name="uniq_shipment_number")]

    def __str__(self):
        return self.number


class ShipmentLine(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="lines")
    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT, related_name="shipment_lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quote_item = models.ForeignKey(
        "sales.QuoteItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    quantity = models.PositiveIntegerField()
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    cell = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        verbose_name = _("Строка отгрузки")
        verbose_name_plural = _("Строки отгрузки")
        ordering = ["shipment_id", "id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="shipment_line_quantity_positive")]
