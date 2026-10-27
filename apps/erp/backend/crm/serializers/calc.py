"""Схемы запросов и ответов «Расчёта по заявке» (D2-1, `crm.views.calc`). Ответы собирает `crm.services.calculation`
словарями; сериализаторы ниже — их явная схема для OpenAPI (`/api/v1/calc/*`) и проверка тел запросов."""

from rest_framework import serializers

ZONES = ("goods", "services", "payment_terms")
LINE_ZONES = ("goods", "services")
LINE_KINDS = ("goods", "goods_to_order", "service")
#: Тип строки без карточки и карточки каталога: товар или услуга.
ITEM_KINDS = ("goods", "service")
VISA_STATES = ("none", "waiting", "done")
CALC_STATES = ("not_started", "in_progress", "returned", "at_director", "rejected", "approved")
READY_BLOCKERS = ("not_started", "not_draft", "no_lines", "visas_missing")


class CalcDealSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    stage_code = serializers.CharField()
    client_name = serializers.CharField(allow_null=True)
    manager_name = serializers.CharField(allow_null=True)


class CalcAssigneeSerializer(serializers.Serializer):
    crm_user_id = serializers.IntegerField()
    zone = serializers.ChoiceField(choices=ZONES)
    name = serializers.CharField(allow_null=True)


class CalcVisaStatesSerializer(serializers.Serializer):
    stock = serializers.ChoiceField(choices=VISA_STATES)
    supply = serializers.ChoiceField(choices=VISA_STATES)
    engineer = serializers.ChoiceField(choices=VISA_STATES)


class CalcTaskRowSerializer(serializers.Serializer):
    deal = CalcDealSerializer()
    letter_number = serializers.CharField()
    due = serializers.DateField()
    state = serializers.ChoiceField(choices=CALC_STATES)
    lines = serializers.IntegerField()
    visas = CalcVisaStatesSerializer()
    assignees = CalcAssigneeSerializer(many=True)


class CalcTaskListSerializer(serializers.Serializer):
    results = CalcTaskRowSerializer(many=True)


class CalcTaskBriefSerializer(serializers.Serializer):
    letter_number = serializers.CharField()
    letter_subject = serializers.CharField(allow_blank=True)
    resolution_text = serializers.CharField(allow_blank=True)
    decided_at = serializers.DateTimeField()
    decided_by_name = serializers.CharField(allow_null=True)
    due = serializers.DateField()
    min_margin_pct = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    assignees = CalcAssigneeSerializer(many=True)


class CalcRequestSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True)
    lines = serializers.IntegerField()


class CalcQuoteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    version = serializers.IntegerField()
    number = serializers.CharField(allow_null=True)
    state = serializers.ChoiceField(choices=CALC_STATES)
    director_comment = serializers.CharField(allow_null=True)
    vat_rate = serializers.DecimalField(max_digits=5, decimal_places=2)


class CalcStockSerializer(serializers.Serializer):
    on_hand = serializers.IntegerField(allow_null=True)
    cell = serializers.CharField(allow_null=True)
    reserved = serializers.IntegerField(allow_null=True)


class CalcSupplierSerializer(serializers.Serializer):
    name = serializers.CharField()
    lead_days = serializers.IntegerField(allow_null=True)
    min_order_qty = serializers.IntegerField()
    price_valid_until = serializers.DateField(allow_null=True)
    offer_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    offer_currency = serializers.CharField(allow_null=True)


class CalcVisaSerializer(serializers.Serializer):
    by = serializers.CharField()
    at = serializers.DateTimeField()


class CalcLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    position = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    product_id = serializers.IntegerField(allow_null=True)
    product_name = serializers.CharField(allow_null=True)
    kind = serializers.ChoiceField(choices=LINE_KINDS)
    zone = serializers.ChoiceField(choices=LINE_ZONES)
    quantity = serializers.IntegerField()
    unit = serializers.CharField(allow_blank=True)
    stock = CalcStockSerializer()
    supplier = CalcSupplierSerializer(allow_null=True)
    lead_days = serializers.IntegerField(allow_null=True)
    purchase_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    purchase_currency = serializers.CharField()
    crew_rate = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    crew_days = serializers.DecimalField(max_digits=6, decimal_places=1, allow_null=True)
    cost = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    client_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    markup_pct = serializers.DecimalField(max_digits=7, decimal_places=1, allow_null=True)
    visa = CalcVisaSerializer(allow_null=True)
    group = serializers.ChoiceField(choices=("stock", "supply", "engineer"))
    can_edit = serializers.BooleanField()


class CalcTotalsSerializer(serializers.Serializer):
    purchase = serializers.DecimalField(max_digits=16, decimal_places=2)
    client = serializers.DecimalField(max_digits=16, decimal_places=2)
    markup_pct = serializers.DecimalField(max_digits=7, decimal_places=1, allow_null=True)
    vat_included = serializers.BooleanField()


class CalcVisaGroupSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=VISA_STATES)
    total = serializers.IntegerField()
    signed = serializers.IntegerField()
    by = serializers.ListField(child=serializers.CharField())


class CalcVisaGroupsSerializer(serializers.Serializer):
    stock = CalcVisaGroupSerializer()
    supply = CalcVisaGroupSerializer()
    engineer = CalcVisaGroupSerializer()


class CalcReadySerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    blocker = serializers.ChoiceField(choices=READY_BLOCKERS, allow_null=True)
    missing = serializers.IntegerField()


class CalcRightsSerializer(serializers.Serializer):
    goods = serializers.BooleanField()
    services = serializers.BooleanField()
    build = serializers.BooleanField()
    cost = serializers.BooleanField()


class CalcSheetSerializer(serializers.Serializer):
    deal = CalcDealSerializer()
    task = CalcTaskBriefSerializer()
    request = CalcRequestSerializer()
    quote = CalcQuoteSerializer(allow_null=True)
    lines = CalcLineSerializer(many=True)
    totals = CalcTotalsSerializer()
    visas = CalcVisaGroupsSerializer()
    ready = CalcReadySerializer()
    rights = CalcRightsSerializer()


class CalcLinesCreatedSerializer(CalcSheetSerializer):
    created = serializers.ListField(child=serializers.IntegerField())


# ── запросы ────────────────────────────────────────────────────────────────────────────────────────────────────────


class CalcLineInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000, required=False, default=1)
    unit = serializers.CharField(max_length=32, allow_blank=True, required=False, default="")
    kind = serializers.ChoiceField(choices=ITEM_KINDS, required=False, default="goods")
    product_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    article = serializers.CharField(max_length=120, allow_blank=True, required=False, default="")
    note = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="")


class CalcLinesInSerializer(serializers.Serializer):
    lines = CalcLineInSerializer(many=True, allow_empty=False)


class CalcLinePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=500, required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000, required=False)
    unit = serializers.CharField(max_length=32, allow_blank=True, required=False)
    lead_days = serializers.IntegerField(min_value=0, max_value=3650, required=False, allow_null=True)
    purchase_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    purchase_currency = serializers.CharField(max_length=3, min_length=3, required=False)
    crew_rate = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, allow_null=True)
    crew_days = serializers.DecimalField(max_digits=6, decimal_places=1, min_value=0, required=False, allow_null=True)
    client_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    product_id = serializers.IntegerField(required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=ITEM_KINDS, required=False)


class CalcParseInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=20000, allow_blank=True, required=False, default="")


class CalcJobSerializer(serializers.Serializer):
    task_id = serializers.CharField()


class CalcCatalogItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    article = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=ITEM_KINDS)
    on_hand = serializers.IntegerField()
    supplier_name = serializers.CharField(allow_null=True)
    lead_days = serializers.IntegerField(allow_null=True)


class CalcCatalogSerializer(serializers.Serializer):
    results = CalcCatalogItemSerializer(many=True)


class CalcErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    missing = serializers.IntegerField(required=False)
    zone = serializers.CharField(required=False)
