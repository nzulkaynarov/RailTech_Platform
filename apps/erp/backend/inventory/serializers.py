"""Схемы запросов и ответов «Склада» (D2-2, `inventory.views`): остатки, резервы, отгрузки, выбор поставщика.
Ответы собирают `inventory.services.overview` и `inventory.services.stock` словарями; сериализаторы — их явная схема для
OpenAPI (`/api/v1/stock/*`) и проверка тел запросов."""

from rest_framework import serializers

RESERVATION_STATUSES = ("active", "released", "fulfilled")
ORDER_STATUSES = ("draft", "sent", "confirmed", "received", "cancelled")


class StockDealRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(allow_null=True, help_text="Номер ЗВ/ПР (`Deal.number`)")
    client_name = serializers.CharField(allow_null=True)


class StockRightsSerializer(serializers.Serializer):
    manage = serializers.BooleanField(help_text="Резервы, корректировки, заказы поставщикам, приёмка (`supply.manage`)")
    ship = serializers.BooleanField(help_text="Отгрузки по проектам (`fulfillment.manage`)")


class StockCellSerializer(serializers.Serializer):
    cell = serializers.CharField(allow_null=True, help_text="Пусто — товар лежит без ячейки")
    on_hand = serializers.IntegerField()


class StockRowSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    on_hand = serializers.IntegerField()
    reserved = serializers.IntegerField(help_text="Остаток резервов действующих проектов")
    free = serializers.IntegerField(help_text="Свободный остаток: остаток − резервы")
    incoming = serializers.IntegerField(help_text="Ожидается по отправленным и подтверждённым заказам поставщикам")
    next_expected = serializers.DateField(allow_null=True)
    cells = StockCellSerializer(many=True)


class StockBalanceListSerializer(serializers.Serializer):
    results = StockRowSerializer(many=True)
    rights = StockRightsSerializer()


class StockReservationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    deal = StockDealRefSerializer()
    quote_item_id = serializers.IntegerField(allow_null=True)
    quantity = serializers.IntegerField()
    shipped_quantity = serializers.IntegerField()
    remaining = serializers.IntegerField()
    status = serializers.ChoiceField(choices=RESERVATION_STATUSES)
    created_at = serializers.DateTimeField()
    created_by_name = serializers.CharField(allow_null=True)


class StockReservationListSerializer(serializers.Serializer):
    results = StockReservationSerializer(many=True)


class StockIncomingOrderSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=ORDER_STATUSES)
    supplier_name = serializers.CharField()
    expected_date = serializers.DateField(allow_null=True)
    quantity_left = serializers.IntegerField()


class StockMovementSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("receipt", "shipment", "adjustment"))
    quantity = serializers.IntegerField(help_text="Плюс — приход, минус — расход")
    cell = serializers.CharField(allow_null=True)
    at = serializers.DateTimeField()
    by_name = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)


class StockProductSerializer(StockRowSerializer):
    reservations = StockReservationSerializer(many=True)
    incoming_orders = StockIncomingOrderSerializer(many=True)
    movements = StockMovementSerializer(many=True)
    rights = StockRightsSerializer()


class StockShipmentLineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    cell = serializers.CharField(allow_null=True)


class StockShipmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(help_text="Внутренняя накладная ОТГ-ГГГГ-NNN")
    deal = StockDealRefSerializer()
    tracking = serializers.CharField(allow_null=True)
    carrier = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    shipped_at = serializers.DateTimeField()
    shipped_by_name = serializers.CharField(allow_null=True)
    lines = StockShipmentLineSerializer(many=True)


class StockShipmentListSerializer(serializers.Serializer):
    results = StockShipmentSerializer(many=True)
    rights = StockRightsSerializer()


class StockSupplierSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    inn = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_null=True, help_text="Адрес для писем: почта компании или основного контакта")


class StockSupplierListSerializer(serializers.Serializer):
    results = StockSupplierSerializer(many=True)


class StockErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Код отказа (`UPPER_SNAKE`)")
    fields = serializers.DictField(
        required=False,
        help_text="`VALIDATION_FAILED`: ошибки полей тела запроса — поле → список кодов или вложенные ошибки",
    )
    free = serializers.IntegerField(required=False, help_text="`NOT_ENOUGH_STOCK`: сколько можно взять")
    max = serializers.IntegerField(
        required=False, help_text="`QUANTITY_OUT_OF_RANGE`: наибольшее допустимое количество"
    )
    reserved = serializers.IntegerField(required=False, help_text="`BELOW_RESERVED`: сколько в резервах")
    on_hand = serializers.IntegerField(required=False)
    shipped = serializers.IntegerField(required=False, help_text="`BELOW_SHIPPED`: уже отгружено")
    current = serializers.CharField(
        required=False, help_text="`TRANSITION_NOT_ALLOWED`, `ORDER_NOT_CONFIRMED`: текущий статус"
    )
    target = serializers.CharField(required=False, help_text="`TRANSITION_NOT_ALLOWED`: куда хотели перейти")


# ── запросы ────────────────────────────────────────────────────────────────────────────────────────────────────────


class StockAdjustInSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(help_text="Плюс — оприходовать, минус — списать; не ноль")
    cell = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("QUANTITY_REQUIRED")
        return value


class StockReserveInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    quote_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class StockShipLineInSerializer(serializers.Serializer):
    reservation_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class StockShipInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    lines = StockShipLineInSerializer(many=True, allow_empty=False, max_length=100)
    tracking = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    carrier = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
