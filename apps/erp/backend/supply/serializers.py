"""Схемы запросов и ответов «Закупок» (D2-2, `supply.views`): заказы поставщикам, приёмка, запросы цен, просрочка.
Ответы собирают `supply.services` и `inventory.services.overview` словарями; сериализаторы — их явная схема для OpenAPI
(`/api/v1/stock/*`) и проверка тел запросов."""

from inventory.serializers import StockDealRefSerializer, StockRightsSerializer
from rest_framework import serializers

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
    send = serializers.BooleanField()
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
    quantity = serializers.IntegerField()
    received_quantity = serializers.IntegerField()
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
    actions = OrderActionsSerializer()


class OrderListSerializer(serializers.Serializer):
    results = OrderRowSerializer(many=True)
    rights = OrderRightsSerializer()


class OrderLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    position = serializers.IntegerField()
    product_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField()
    received_quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    line_total = serializers.DecimalField(max_digits=16, decimal_places=2, allow_null=True)
    deal = StockDealRefSerializer(allow_null=True)
    quote_item_id = serializers.IntegerField(allow_null=True)


class ReceiptLineSerializer(serializers.Serializer):
    order_line_id = serializers.IntegerField()
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    cell = serializers.CharField(allow_null=True)


class OrderReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    received_at = serializers.DateTimeField()
    received_by_name = serializers.CharField(allow_null=True)
    supplier_doc = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    lines = ReceiptLineSerializer(many=True)


class OrderLogSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=LOG_KINDS)
    at = serializers.DateTimeField()
    by_name = serializers.CharField(allow_null=True)
    detail = serializers.CharField(allow_null=True)


class OrderDetailSerializer(OrderRowSerializer):
    note = serializers.CharField(allow_blank=True)
    sent_at = serializers.DateTimeField(allow_null=True)
    sent_to = serializers.CharField(allow_null=True)
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
    quantity = serializers.IntegerField()
    received_quantity = serializers.IntegerField()
    deal = StockDealRefSerializer(allow_null=True)


class DoneReceiptLineSerializer(serializers.Serializer):
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    cell = serializers.CharField(allow_null=True)


class DoneReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    supplier_name = serializers.CharField()
    received_at = serializers.DateTimeField()
    received_by_name = serializers.CharField(allow_null=True)
    supplier_doc = serializers.CharField(allow_null=True)
    quantity = serializers.IntegerField()
    lines = DoneReceiptLineSerializer(many=True)


class ReceiptsSerializer(serializers.Serializer):
    pending = PendingReceiptLineSerializer(many=True)
    done = DoneReceiptSerializer(many=True)
    rights = StockRightsSerializer()


class PriceRequestLineSerializer(serializers.Serializer):
    quote_item_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField()
    unit = serializers.CharField(allow_blank=True)


class PriceRequestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    supplier = OrderSupplierSerializer()
    deal_id = serializers.IntegerField(allow_null=True)
    deal_number = serializers.CharField(allow_null=True)
    requested_at = serializers.DateTimeField()
    requested_by_name = serializers.CharField(allow_null=True)
    to_email = serializers.CharField()
    subject = serializers.CharField()
    note = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=("sent", "failed"))
    error = serializers.CharField(allow_null=True)
    answered_at = serializers.DateTimeField(allow_null=True)
    answered_by_name = serializers.CharField(allow_null=True)
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


# ── запросы ────────────────────────────────────────────────────────────────────────────────────────────────────────


class OrderLineInSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, min_value=1, help_text="Строка этого заказа (правка); без id — новая")
    product_id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    article = serializers.CharField(required=False, allow_blank=True, max_length=120, default="")
    unit = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=10_000_000)
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
    currency = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=3)
    lines = OrderLineInSerializer(many=True, allow_empty=False, max_length=200)


class OrderFromDealInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    supplier_id = serializers.IntegerField(min_value=1)


class OrderPatchInSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(required=False, min_value=1)
    expected_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    currency = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=3)
    lines = OrderLineInSerializer(many=True, required=False, allow_empty=False, max_length=200)


class OrderSendInSerializer(serializers.Serializer):
    to_email = serializers.EmailField(required=False, allow_blank=True, default="")


class OrderConfirmInSerializer(serializers.Serializer):
    expected_date = serializers.DateField(required=False, allow_null=True)


class OrderCancelInSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class ReceiptLineInSerializer(serializers.Serializer):
    order_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    cell = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")


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
