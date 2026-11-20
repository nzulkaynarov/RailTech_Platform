"""Схемы запросов и ответов «Закупок» (D2-2, `supply.views`): заказы поставщикам, приёмка, запросы цен, просрочка.
Ответы собирают `supply.services` и `inventory.services.overview` словарями; сериализаторы — их явная схема для OpenAPI
(`/api/v1/stock/*`) и проверка тел запросов."""

from decimal import Decimal

from inventory.serializers import TRACKING_CLASSES, StockDealRefSerializer, StockRightsSerializer
from rest_framework import serializers

from catalog.item_ref import ItemRefSerializer
from core.person_ref import PersonRefSerializer
from core.quantity import QuantityField

ORDER_STATUSES = ("draft", "sent", "confirmed", "received", "cancelled")
RECEIPT_STATES = ("none", "partial", "full")
LOG_KINDS = ("created", "edited", "sent", "confirmed", "receipt", "received", "cancelled", "overdue")


class OrderRightsSerializer(StockRightsSerializer):
    prices = serializers.BooleanField(help_text="Видит цены поставщиков (`quote.view_cost_margin` или зона товаров)")


class OrderSupplierSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.CharField(required=False, allow_null=True, help_text="Только в карточке заказа")


class OrderActionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()
    send = serializers.BooleanField(help_text="Черновик полный: у всех строк цена и есть ожидаемая дата (СЦ-10)")
    request_price = serializers.BooleanField(
        help_text="Черновик с строками без цены: «Запросить цену» у партнёра (СЦ-10)"
    )
    confirm = serializers.BooleanField()
    receive = serializers.BooleanField()
    cancel = serializers.BooleanField()


class OrderRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(help_text="ЗП-ГГГГ-NNN")
    status = serializers.ChoiceField(choices=ORDER_STATUSES)
    supplier = OrderSupplierSerializer()
    expected_date = serializers.DateField(allow_null=True)
    overdue = serializers.BooleanField(
        help_text="Ожидаемая дата прошла, заказ отправлен или подтверждён, но не получен"
    )
    days_overdue = serializers.IntegerField(allow_null=True)
    currency = serializers.CharField(allow_null=True)
    lines_count = serializers.IntegerField()
    quantity = QuantityField()
    received_quantity = QuantityField()
    receipt_state = serializers.ChoiceField(choices=RECEIPT_STATES)
    total = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        allow_null=True,
        help_text="Сумма заказа — только с правом видеть цены поставщиков",
    )
    projects = StockDealRefSerializer(many=True)
    created_at = serializers.DateTimeField()
    created_by_name = serializers.CharField(allow_null=True)
    created_by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    actions = OrderActionsSerializer()


class OrderListSerializer(serializers.Serializer):
    results = OrderRowSerializer(many=True)
    rights = OrderRightsSerializer()


class OrderLineOfferSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    incoterms = serializers.CharField(allow_null=True, help_text="Базис поставки цены поставщика")
    valid_until = serializers.DateField(allow_null=True, help_text="Цена действует до")
    expired = serializers.BooleanField()


class OrderLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    position = serializers.IntegerField()
    product_id = serializers.IntegerField(allow_null=True)
    item = ItemRefSerializer(allow_null=True, help_text="Позиция каталога (ЕД-4); null — строка без карточки")
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    quantity = QuantityField()
    received_quantity = QuantityField()
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    line_total = serializers.DecimalField(max_digits=16, decimal_places=2, allow_null=True)
    deal = StockDealRefSerializer(allow_null=True)
    quote_item_id = serializers.IntegerField(allow_null=True)
    offer = OrderLineOfferSerializer(allow_null=True, help_text="Цена поставщика, из которой создана строка")
    tracking = serializers.ChoiceField(choices=TRACKING_CLASSES, help_text="Учёт единиц товара по категории")
    requires_doc = serializers.BooleanField(help_text="Категория требует документ соответствия на приёмке")


class DoneReceiptLineSerializer(serializers.Serializer):
    name = serializers.CharField()
    quantity = QuantityField()
    cell = serializers.CharField(allow_null=True)
    units = serializers.ListField(child=serializers.CharField(), help_text="Принятые серийные или номер партии")
    expiry_date = serializers.DateField(allow_null=True)
    doc_number = serializers.CharField(allow_null=True)
    doc_valid_until = serializers.DateField(allow_null=True)


class ReceiptLineSerializer(DoneReceiptLineSerializer):
    order_line_id = serializers.IntegerField()


class OrderReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    received_at = serializers.DateTimeField()
    received_by_name = serializers.CharField(allow_null=True)
    received_by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    supplier_doc = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    lines = ReceiptLineSerializer(many=True)


class OrderLogSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=LOG_KINDS)
    at = serializers.DateTimeField()
    by_name = serializers.CharField(allow_null=True)
    by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    detail = serializers.CharField(allow_null=True)


class OrderMailSerializer(serializers.Serializer):
    """Итог письма партнёру (0.10, FR-12): в очереди почтового сервиса, отправлено или не отправлено с кодом причины."""

    state = serializers.ChoiceField(choices=["queued", "sent", "failed"])
    reason = serializers.CharField(
        allow_null=True, help_text="Код причины неудачи: smtp_not_configured, rejected, auth_failed, unavailable…"
    )


class OrderSendMissingSerializer(serializers.Serializer):
    prices = serializers.IntegerField(help_text="Сколько строк без цены")
    date = serializers.BooleanField(help_text="Нет ожидаемой даты")


class OrderPriceRequestStateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    requested_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=("sent", "failed"))
    answered_at = serializers.DateTimeField(allow_null=True)


class OrderDetailSerializer(OrderRowSerializer):
    note = serializers.CharField(allow_blank=True, help_text="Внутреннее примечание: партнёру не уходит")
    partner_note = serializers.CharField(
        allow_blank=True, help_text="Комментарий партнёру: в письме с заказом и в кабинете"
    )
    send_missing = OrderSendMissingSerializer(
        allow_null=True,
        help_text="СЦ-10: чего не хватает черновику для отправки партнёру; полный или не черновик — null",
    )
    price_request = OrderPriceRequestStateSerializer(
        allow_null=True, help_text="СЦ-10: последний запрос цены из этого черновика; не было — null"
    )
    sent_at = serializers.DateTimeField(allow_null=True)
    sent_to = serializers.CharField(allow_null=True)
    mail = OrderMailSerializer(allow_null=True)
    confirmed_at = serializers.DateTimeField(allow_null=True)
    received_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancel_reason = serializers.CharField(allow_null=True)
    lines = OrderLineSerializer(many=True)
    receipts = OrderReceiptSerializer(many=True)
    log = OrderLogSerializer(many=True)
    rights = OrderRightsSerializer()


class PendingReceiptLineSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    supplier_name = serializers.CharField()
    expected_date = serializers.DateField(allow_null=True)
    overdue = serializers.BooleanField()
    order_line_id = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    quantity = QuantityField()
    received_quantity = QuantityField()
    deal = StockDealRefSerializer(allow_null=True)
    tracking = serializers.ChoiceField(choices=TRACKING_CLASSES)
    requires_doc = serializers.BooleanField()


class DoneReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    supplier_name = serializers.CharField()
    received_at = serializers.DateTimeField()
    received_by_name = serializers.CharField(allow_null=True)
    received_by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    supplier_doc = serializers.CharField(allow_null=True)
    quantity = QuantityField()
    lines = DoneReceiptLineSerializer(many=True)


class ReceiptsSerializer(serializers.Serializer):
    pending = PendingReceiptLineSerializer(many=True)
    done = DoneReceiptSerializer(many=True)
    rights = StockRightsSerializer()


class PriceRequestLineSerializer(serializers.Serializer):
    quote_item_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    quantity = QuantityField()
    unit = serializers.CharField(allow_blank=True)


class PriceRequestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    supplier = OrderSupplierSerializer()
    deal_id = serializers.IntegerField(allow_null=True)
    deal_number = serializers.CharField(allow_null=True)
    supplier_order_id = serializers.IntegerField(
        allow_null=True, help_text="Черновик заказа, из которого запрос (СЦ-10)"
    )
    supplier_order_number = serializers.CharField(allow_null=True)
    requested_at = serializers.DateTimeField()
    requested_by_name = serializers.CharField(allow_null=True)
    requested_by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    to_email = serializers.CharField()
    subject = serializers.CharField()
    note = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=("sent", "failed"))
    error = serializers.CharField(allow_null=True)
    answered_at = serializers.DateTimeField(allow_null=True)
    answered_by_name = serializers.CharField(allow_null=True)
    answered_by = PersonRefSerializer(allow_null=True, help_text="Сотрудник со ссылкой на CRM (СУЩ-3)")
    answer_note = serializers.CharField(allow_null=True)
    lines = PriceRequestLineSerializer(many=True)


class PriceRequestListSerializer(serializers.Serializer):
    results = PriceRequestSerializer(many=True)


class OverdueOrderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=ORDER_STATUSES)
    supplier_name = serializers.CharField()
    expected_date = serializers.DateField()
    days_overdue = serializers.IntegerField()


class OverdueListSerializer(serializers.Serializer):
    results = OverdueOrderSerializer(many=True)


class SupplyTaskSerializer(serializers.Serializer):
    """Строка списка дел снабженца (план 0.7, FR-6): заказ партнёру или заявка на партнёрство."""

    kind = serializers.ChoiceField(
        choices=["send_order", "partner_date_change", "receive_goods", "partner_application"],
        help_text="send_order — черновик не отправлен; partner_date_change — партнёр просит перенести дату; "
        "receive_goods — партнёр отгрузил, товар не принят; partner_application — заявка на партнёрство ждёт решения",
    )
    id = serializers.IntegerField(help_text="Заказ партнёру или заявка на партнёрство")
    number = serializers.CharField(allow_null=True, help_text="Номер заказа; у заявки на партнёрство — null")
    supplier_name = serializers.CharField(help_text="Партнёр или компания-заявитель")
    since = serializers.DateTimeField(allow_null=True, help_text="С какого момента дело ждёт снабженца")
    date = serializers.DateField(required=False, help_text="partner_date_change: на какую дату просит партнёр")
    note = serializers.CharField(required=False, allow_null=True, help_text="Причина переноса или накладная отгрузки")
    status = serializers.CharField(required=False, help_text="partner_application: submitted или candidate_agreed")


class SupplyTaskListSerializer(serializers.Serializer):
    results = SupplyTaskSerializer(many=True)


# ── запросы ────────────────────────────────────────────────────────────────────────────────────────────────────────


class OrderLineInSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, min_value=1, help_text="Строка этого заказа (правка); без id — новая")
    product_id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    article = serializers.CharField(required=False, allow_blank=True, max_length=120, default="")
    unit = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    quantity = QuantityField(min_value=Decimal("0.001"), max_value=Decimal("10000000"))
    unit_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Цена поставщика за единицу; ставит только держатель права видеть цены поставщиков",
    )
    deal_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    quote_item_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class OrderCreateInSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(min_value=1)
    expected_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    partner_note = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    currency = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=3)
    lines = OrderLineInSerializer(many=True, allow_empty=False, max_length=200)


class OrderFromDealInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    supplier_id = serializers.IntegerField(min_value=1)


class OrderPatchInSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(required=False, min_value=1)
    expected_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    partner_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
        help_text="Только в черновике: отправленный заказ не меняется",
    )
    currency = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=3)
    lines = OrderLineInSerializer(many=True, required=False, allow_empty=False, max_length=200)


class OrderSendInSerializer(serializers.Serializer):
    to_email = serializers.EmailField(required=False, allow_blank=True, default="")


class OrderPriceRequestInSerializer(serializers.Serializer):
    """«Запросить цену» из черновика заказа (СЦ-10): без `line_ids` — все строки без цены."""

    line_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, min_length=1, max_length=100, help_text="Строки заказа"
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    to_email = serializers.EmailField(required=False, allow_blank=True, default="")


class OrderConfirmInSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)


class OrderCancelInSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class ReceiptLineInSerializer(serializers.Serializer):
    order_line_id = serializers.IntegerField(min_value=1)
    quantity = QuantityField(min_value=Decimal("0.001"))
    cell = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    # ADR-0021: по классу категории; для N не передаются.
    serials = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=True),
        required=False,
        default=list,
        max_length=1000,
        help_text="Серийные номера (S): их число = количеству",
    )
    lot = serializers.CharField(required=False, allow_blank=True, max_length=100, default="", help_text="Партия (L)")
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None, help_text="Годен до (L)")
    doc_number = serializers.CharField(
        required=False, allow_blank=True, max_length=100, default="", help_text="№ сертификата или декларации"
    )
    doc_valid_until = serializers.DateField(
        required=False, allow_null=True, default=None, help_text="Документ соответствия действует до"
    )


class ReceiptInSerializer(serializers.Serializer):
    lines = ReceiptLineInSerializer(many=True, allow_empty=False, max_length=200)
    supplier_doc = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class PriceRequestInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    supplier_id = serializers.IntegerField(min_value=1)
    line_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100, help_text="Строки расчёта"
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    to_email = serializers.EmailField(required=False, allow_blank=True, default="")


class PriceRequestAnswerInSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
