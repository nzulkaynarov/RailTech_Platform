"""Схемы запросов и ответов «Склада» (D2-2, `inventory.views`): остатки, резервы, отгрузки, выбор поставщика.
Ответы собирают `inventory.services.overview` и `inventory.services.stock` словарями; сериализаторы — их явная схема для
OpenAPI (`/api/v1/stock/*`) и проверка тел запросов."""

from rest_framework import serializers

from catalog.constants import TrackingClass

RESERVATION_STATUSES = ("active", "released", "fulfilled")
#: Учёт единиц категории (ADR-0021): серийный, партия, только количество.
TRACKING_CLASSES = TrackingClass.choices
TRACE_KINDS = ("serial", "lot")
TRACE_STATUSES = ("in_stock", "shipped")
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


class StockTraceUnitShortSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=TRACE_KINDS)
    number = serializers.CharField(help_text="Серийный номер или номер партии изготовителя")
    expiry_date = serializers.DateField(allow_null=True, help_text="Годен до (партия)")
    available = serializers.IntegerField(help_text="Сколько ещё на складе: серийный — 1, партия — остаток партии")


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
    tracking = serializers.ChoiceField(choices=TRACKING_CLASSES, help_text="Учёт единиц товара по его категории")
    units = StockTraceUnitShortSerializer(
        many=True, help_text="Свободные серийные или партии товара — выбор при отгрузке (S/L); у N пусто"
    )


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


class StockShipmentUnitSerializer(serializers.Serializer):
    number = serializers.CharField()
    quantity = serializers.IntegerField()


class StockShipmentLineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    cell = serializers.CharField(allow_null=True)
    units = StockShipmentUnitSerializer(many=True, help_text="Серийные или партии, ушедшие этой строкой")


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
    expected = serializers.IntegerField(
        required=False, help_text="`SERIALS_REQUIRED`, `SERIALS_COUNT_MISMATCH`, `UNITS_*`: сколько номеров нужно"
    )
    given = serializers.IntegerField(required=False, help_text="`*_COUNT_MISMATCH`: сколько передано")
    number = serializers.CharField(
        required=False, help_text="`SERIAL_DUPLICATE`, `SERIAL_EXISTS`, `UNIT_NOT_AVAILABLE`: номер, о котором речь"
    )


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


class StockShipUnitInSerializer(serializers.Serializer):
    unit_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, required=False, default=1, help_text="Серийный — 1")


class StockShipLineInSerializer(serializers.Serializer):
    reservation_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    units = StockShipUnitInSerializer(
        many=True, required=False, default=list, max_length=1000, help_text="Обязательно для товаров S/L (ADR-0021)"
    )


class StockShipInSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(min_value=1)
    lines = StockShipLineInSerializer(many=True, allow_empty=False, max_length=100)
    tracking = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    carrier = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


# ── прослеживаемость (ADR-0021) ────────────────────────────────────────────────────────────────────────────────────


class StockTraceProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)


class StockTraceOriginSerializer(serializers.Serializer):
    receipt_id = serializers.IntegerField()
    received_at = serializers.DateTimeField()
    supplier_doc = serializers.CharField(allow_null=True)
    order_id = serializers.IntegerField()
    order_number = serializers.CharField()
    supplier_name = serializers.CharField()
    manufacturer = serializers.CharField(allow_null=True)
    doc_number = serializers.CharField(allow_null=True, help_text="№ сертификата или декларации на приёмке")
    doc_valid_until = serializers.DateField(allow_null=True)
    deal = StockDealRefSerializer(allow_null=True, help_text="Проект, под который заказывали")


class StockTraceDestinationSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    shipment_number = serializers.CharField()
    shipped_at = serializers.DateTimeField()
    quantity = serializers.IntegerField()
    deal = StockDealRefSerializer()


class StockTraceUnitSerializer(StockTraceUnitShortSerializer):
    quantity = serializers.IntegerField()
    shipped_quantity = serializers.IntegerField()
    status = serializers.ChoiceField(choices=TRACE_STATUSES)
    product = StockTraceProductSerializer()
    origin = StockTraceOriginSerializer(help_text="Откуда: приёмка, заказ, поставщик, изготовитель, документ")
    destinations = StockTraceDestinationSerializer(many=True, help_text="Куда: отгрузки, клиент, проект")


class StockTraceListSerializer(serializers.Serializer):
    results = StockTraceUnitSerializer(many=True)
