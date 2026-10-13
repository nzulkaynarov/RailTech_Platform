from rest_framework import serializers

from .models import Country, Currency, DeliveryBasis, UnitOfMeasure


# Код справочника — бизнес-ключ, а не текст: у существующей строки он только на чтение.
#
# По `code` сравнивается логика во всём продукте (Rule 2: сравнивать по коду, а не по
# переведённому имени). `PATCH {"code": "..."}` проходил как обычная правка поля, и строка
# оставалась на месте, а ветки в сервисах, спрашивающие прежний код, переставали срабатывать —
# молча, без единой ошибки. Переименование валюты `UZS` в такой ситуации не «переименование»,
# а исчезновение валюты для всего кода, который её знает.
#
# Завести НОВЫЙ код по-прежнему можно: запрет только на переписывание существующего — так же
# устроены стабильные идентификаторы у эталонов (Stripe `lookup_key`, Odoo external ID:
# заводится при создании, дальше не переименовывается, вместо правки создают новую запись).
#
# Разбор ЗДЕСЬ, а не докстрингом: drf-spectacular берёт докстринг первого класса в цепочке как
# `description` схемы, и внутреннее обоснование уехало бы в публичный контракт API — четырьмя
# копиями сразу (замер по диффу schema.json 25-08).
class _StableCodeMixin:
    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and "code" in fields:
            fields["code"].read_only = True
        return fields


class CountrySerializer(_StableCodeMixin, serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = "__all__"


class CurrencySerializer(_StableCodeMixin, serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = "__all__"


class UnitOfMeasureSerializer(_StableCodeMixin, serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = "__all__"


class DeliveryBasisSerializer(_StableCodeMixin, serializers.ModelSerializer):
    class Meta:
        model = DeliveryBasis
        fields = "__all__"
