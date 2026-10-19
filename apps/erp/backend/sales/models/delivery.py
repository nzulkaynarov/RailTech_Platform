from django.db import models
from django.utils.translation import gettext_lazy as _


class DeliveryLineStatus(models.TextChoices):
    """Статусы строки поставки — как `DeliveryStatus` в `packages/contracts/openapi/erp-portal.yaml` (0.2.0)."""

    ASSEMBLING = "assembling", _("Комплектуется")
    IN_TRANSIT = "in_transit", _("В пути")
    READY_TO_SHIP = "ready_to_ship", _("Готово к отгрузке")
    SHIPPED = "shipped", _("Отгружено")
    DELIVERED = "delivered", _("Доставлено")
    ACCEPTED = "accepted", _("Принято клиентом")
    DISPUTED = "disputed", _("Оспорено клиентом")


class DeliveryLine(models.Model):
    """Строка поставки = строка подтверждённого заказа клиента (FIX-22, BUSINESS §9 шаг 9).

    Минимальная модель: одна запись на оплачиваемую позицию КП, которое клиент принял. Название, количество и
    единица — снимок на момент подтверждения (подтверждённый заказ не правится). Статус, срок, трек и дату
    отгрузки пока ведёт `Fulfillment` сделки (`sales.services.delivery_lines.sync_delivery_lines` переносит их на
    строки); `accepted` и `disputed` ставит только клиент через портал и дальше они не перезаписываются. Поставки по
    складу и поставщикам (M4) будут писать в эту же модель. Поставщика и цен здесь нет намеренно: клиент видит
    только проекцию.
    """

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="delivery_lines",
        verbose_name=_("Сделка"),
    )
    quote_item = models.OneToOneField(
        "sales.QuoteItem",
        on_delete=models.CASCADE,
        related_name="delivery_line",
        verbose_name=_("Строка заказа"),
        help_text=_("Оплачиваемая позиция подтверждённого КП, которую поставляем"),
    )
    line_no = models.PositiveIntegerField(verbose_name=_("№ строки"), help_text=_("Сквозной номер в заказе, с 1"))
    title = models.CharField(max_length=500, blank=True, default="", verbose_name=_("Название"))
    quantity = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Количество"))
    unit = models.CharField(max_length=32, blank=True, default="", verbose_name=_("Единица"))
    status = models.CharField(
        max_length=16,
        choices=DeliveryLineStatus.choices,
        default=DeliveryLineStatus.ASSEMBLING,
        db_index=True,
        verbose_name=_("Статус"),
    )
    eta = models.DateField(null=True, blank=True, verbose_name=_("Ожидаемая дата"))
    tracking = models.CharField(max_length=128, blank=True, default="", verbose_name=_("Трек-номер"))
    shipped_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Отгружено"))
    accepted_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Принято или оспорено"), help_text=_("Когда клиент принял или оспорил")
    )
    remark = models.TextField(blank=True, default="", verbose_name=_("Замечание клиента"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Строка поставки")
        verbose_name_plural = _("Строки поставки")
        ordering = ["deal_id", "line_no"]

    def __str__(self):
        return f"DeliveryLine #{self.pk} (deal {self.deal_id}, line {self.line_no}, {self.status})"
