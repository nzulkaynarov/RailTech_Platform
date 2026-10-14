from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import Currency, DeliveryBasis

# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Оффер поставщика (Product + Company = Price)
# ────────────────────────────────────────────


class SupplierOffer(models.Model):
    """
    Коммерческое предложение поставщика на конкретный товар.

    Один Product может иметь несколько офферов от разных поставщиков.
    Именно отсюда менеджер берет цены при создании КП (Quote).
    """

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="offers",
        verbose_name=_("Товар"),
        help_text=_("Эталонный товар из каталога PIM"),
    )
    supplier = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="supplier_offers",
        verbose_name=_("Поставщик"),
        help_text=_("Компания-поставщик"),
    )
    supplier_sku = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Артикул поставщика"),
        help_text=_("Внутренний номер товара у поставщика"),
    )

    # Коммерческие условия
    base_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Базовая цена"),
        help_text=_("Цена поставщика за единицу (FCA/EXW)"),
    )
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="offers",
        null=True,
        blank=True,
        verbose_name=_("Валюта"),
        help_text=_("Валюта базовой цены"),
    )
    delivery_basis = models.ForeignKey(
        DeliveryBasis,
        on_delete=models.PROTECT,
        related_name="offers",
        null=True,
        blank=True,
        verbose_name=_("Базис поставки"),
        help_text=_("Условия поставки по Incoterms (FCA, DAP, EXW)"),
    )
    stock_status = models.ForeignKey(
        "catalog.StockStatus",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offers",
        verbose_name=_("Статус наличия"),
        help_text=_("Текущий статус наличия у поставщика"),
    )
    delivery_lead_time = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Срок поставки"),
        help_text=_("Ориентировочный срок поставки (напр. '14-21 дн.') — свободный текст"),
    )
    # Наличие на складе (ATP — available-to-promise). stock_quantity единиц поставщик может
    # отгрузить со склада за in_stock_lead_time_days; остаток заказа едет под заказ за
    # order_lead_time_days. Из этих полей авто-сплитятся транши строки КП (Track B).
    stock_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Остаток на складе"),
        help_text=_("Доступное количество на складе (ATP) для отгрузки в короткий срок"),
    )
    in_stock_lead_time_days = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Срок поставки со склада (дней)"),
        help_text=_("Срок отгрузки единиц, имеющихся на складе (наличие)"),
    )
    order_lead_time_days = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Срок поставки под заказ (дней)"),
        help_text=_("Срок поставки единиц сверх складского остатка (под заказ)"),
    )
    min_order_qty = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Мин. заказ"),
        help_text=_("Минимальное количество для заказа"),
    )

    # Срок действия оффера
    valid_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует с"),
        help_text=_("Дата начала действия предложения"),
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания действия предложения"),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные офферы не отображаются при выборе"),
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
        verbose_name = _("Оффер поставщика")
        verbose_name_plural = _("Каталог: Офферы поставщиков")
        unique_together = [("product", "supplier")]
        ordering = ["base_price"]

    def __str__(self):
        return f"{self.product.name} | {self.supplier.name} | {self.base_price} {self.currency}"
