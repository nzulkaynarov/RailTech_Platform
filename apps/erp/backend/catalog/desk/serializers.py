"""Явные схемы запросов и ответов операций D2-3 (CONVENTIONS ERP §5: каждая операция `/api/v1` описана).

Ответы собирают сервисы `catalog.desk.*` словарями; эти классы нужны схеме OpenAPI и входной проверке формы. Имена
компонентов начинаются с `Desk`. Закрытые поля (`price`, `rate`) — `null` у того, кому ERP их не отдаёт.
"""

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from catalog.desk.items import ALL_KINDS
from catalog.models import Brigade, TechDocument


class Money(serializers.Serializer):
    amount = serializers.CharField(help_text="Сумма строкой с двумя знаками.")
    currency = serializers.CharField(allow_null=True, help_text="Код валюты ISO 4217.")


class DeskUnit(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class DeskRef(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class DeskItemRow(serializers.Serializer):
    id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=list(ALL_KINDS),
        help_text="Тип вычисляется: товар со склада или под заказ, услуга фикс / по этапам / по времени.",
    )
    is_service = serializers.BooleanField()
    unit = DeskUnit(allow_null=True)
    vat_rate = serializers.CharField(allow_null=True, help_text="НДС позиции, %; null — ставка компании по умолчанию.")
    vat_effective = serializers.CharField(
        allow_null=True, help_text="Действующая ставка: своя или компании по умолчанию."
    )
    category = DeskRef(allow_null=True)
    status = serializers.CharField(allow_null=True, help_text="Код статуса карточки: DRAFT, PUBLISHED.")
    offers_count = serializers.IntegerField()
    nearest_valid_until = serializers.DateField(allow_null=True)
    docs_count = serializers.IntegerField()


class DeskOfferSupplier(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class DeskOfferProduct(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField()


class DeskOffer(serializers.Serializer):
    id = serializers.IntegerField()
    supplier = DeskOfferSupplier()
    product = DeskOfferProduct()
    supplier_sku = serializers.CharField()
    price = Money(allow_null=True, help_text="Цена закупки: только с правом на цены поставщиков (иначе null).")
    quota_qty = serializers.IntegerField(help_text="Квота: сколько единиц поставщик готов отгрузить по этой цене.")
    min_order_qty = serializers.IntegerField()
    in_stock_lead_days = serializers.IntegerField()
    order_lead_days = serializers.IntegerField()
    stock_status = serializers.CharField(allow_null=True)
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    is_active = serializers.BooleanField()
    validity = serializers.ChoiceField(choices=["ok", "expiring", "expired"])


class DeskTechDocRef(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    kind = serializers.ChoiceField(choices=TechDocument.Kind.values)


class DeskItemDetail(DeskItemRow):
    description = serializers.CharField()
    gost_drawing = serializers.CharField()
    hs_code = serializers.CharField()
    manufacturer_part_number = serializers.CharField()
    brand = serializers.CharField(allow_null=True)
    offers = DeskOffer(many=True)
    prices_visible = serializers.BooleanField(help_text="Видит ли сотрудник цены поставщиков (иначе price = null).")
    tech_docs = DeskTechDocRef(many=True)


class DeskItemIn(serializers.Serializer):
    """Создание и правка позиции. При правке приходят только изменяемые поля."""

    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    kind = serializers.ChoiceField(required=False, choices=list(ALL_KINDS))
    unit_id = serializers.IntegerField(required=False, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    vat_rate = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Процент 0..100; пусто — по умолчанию компании."
    )


class DeskSupplierRow(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    tin = serializers.CharField()
    country = serializers.CharField(allow_null=True)
    offers_count = serializers.IntegerField()
    expired_count = serializers.IntegerField(help_text="Действующих предложений с истёкшим сроком цены.")
    expiring_count = serializers.IntegerField(help_text="Срок цены истекает в ближайшие 14 дней.")
    nearest_valid_until = serializers.DateField(allow_null=True)


class DeskSupplierDetail(DeskSupplierRow):
    contact_person = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.CharField()
    website = serializers.CharField()
    legal_address = serializers.CharField()
    offers = DeskOffer(many=True)
    prices_visible = serializers.BooleanField()


class DeskMoneyIn(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class DeskOfferIn(serializers.Serializer):
    price = DeskMoneyIn(
        required=False, help_text="Цена закупки; нужно право на цены поставщиков (403 SUPPLIER_PRICES_REQUIRED)."
    )
    quota_qty = serializers.IntegerField(required=False, min_value=0)
    min_order_qty = serializers.IntegerField(required=False, min_value=1)
    in_stock_lead_days = serializers.IntegerField(required=False, min_value=0)
    order_lead_days = serializers.IntegerField(required=False, min_value=0)
    stock_status = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)


class DeskCrewRate(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField(allow_null=True)
    unit = serializers.ChoiceField(choices=Brigade.RateUnit.values)


@extend_schema_serializer(component_name="DeskBrigade")
class DeskBrigadeRow(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=Brigade.Kind.values)
    specialization = serializers.CharField()
    headcount = serializers.IntegerField()
    rate = DeskCrewRate(allow_null=True, help_text="Ставка: держатель зоны услуг или cost_margin; иначе null.")
    rate_visible = serializers.BooleanField()
    note = serializers.CharField()
    is_active = serializers.BooleanField()


class DeskCrewRateIn(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class DeskBrigadeIn(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    kind = serializers.ChoiceField(required=False, choices=Brigade.Kind.values)
    specialization = serializers.CharField(required=False, allow_blank=True, max_length=255)
    headcount = serializers.IntegerField(required=False, min_value=1, max_value=500)
    rate = DeskCrewRateIn(required=False, allow_null=True)
    rate_unit = serializers.ChoiceField(required=False, choices=Brigade.RateUnit.values)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    is_active = serializers.BooleanField(required=False)


class DeskTechDocProduct(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField()


class DeskTechDocDeal(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    client = serializers.CharField()
    stage_code = serializers.CharField(help_text="Код стадии сделки: по нему Платформа составляет номер ЗВ/ПР (B-010).")
    created_at = serializers.DateTimeField()


class DeskTechDoc(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=TechDocument.Kind.values)
    title = serializers.CharField()
    original_name = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    previewable = serializers.BooleanField(
        help_text="PDF и изображения открываются для просмотра; остальное скачивается."
    )
    product = DeskTechDocProduct(allow_null=True)
    deal = DeskTechDocDeal(allow_null=True)
    uploaded_by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class DeskTechDocUpload(serializers.Serializer):
    """multipart/form-data: файл ≤ 20 МБ (PDF, PNG, JPEG, DOC(X), XLS(X)), хотя бы одна привязка — позиция или заявка."""

    file = serializers.FileField()
    kind = serializers.ChoiceField(required=False, choices=TechDocument.Kind.values)
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    product_id = serializers.IntegerField(required=False)
    deal_id = serializers.IntegerField(required=False)


class DeskHsCode(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    unit_name = serializers.CharField()
    extra_unit_name = serializers.CharField()
    level = serializers.IntegerField()
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    is_active = serializers.BooleanField()
    source = serializers.CharField()


class DeskHsCodeIn(serializers.Serializer):
    code = serializers.CharField(required=False, help_text="Только при создании: 2, 4, 6, 8 или 10 цифр.")
    name = serializers.CharField(required=False, allow_blank=True)
    unit_name = serializers.CharField(required=False, allow_blank=True, max_length=64)
    extra_unit_name = serializers.CharField(required=False, allow_blank=True, max_length=64)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_until = serializers.DateField(required=False, allow_null=True)


class DeskExchangeRate(serializers.Serializer):
    id = serializers.IntegerField()
    currency = serializers.CharField()
    rate_to_uzs = serializers.CharField()
    rate_date = serializers.DateField()
    source = serializers.CharField(help_text="CBU (автозагрузка ЦБ РУз) или MANUAL.")
