"""Схемы API отклонения маржи (M1-ERP-08). Ответ собирает `finance.services.margin_deviation`;
сериализаторы описывают его форму для OpenAPI (типы фронтенда) и валидируют ввод факта закупки."""

from rest_framework import serializers


class PurchaseActualSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=8, help_text="Валюта себестоимости строк опорного КП (или UZS).")
    amount = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=32,
        help_text="Фактическая себестоимость в валюте; пусто — как в КП (отклонение только по курсу).",
    )
    rate = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=32,
        help_text="Фактический курс (UZS за 1 ед.); пусто — курс справочника на дату закупки.",
    )
    purchased_on = serializers.DateField(required=False, allow_null=True, help_text="Дата закупки; пусто — сегодня.")
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class ReferenceQuoteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    version = serializers.IntegerField()
    number = serializers.CharField()
    status_code = serializers.CharField()
    frozen_at = serializers.CharField(allow_null=True)
    fx_fixed_at = serializers.CharField(allow_null=True)


class MarginDeviationRowSerializer(serializers.Serializer):
    currency = serializers.CharField()
    lines = serializers.IntegerField(help_text="Строк КП в этой валюте себестоимости.")
    quoted_amount = serializers.CharField(
        help_text="Себестоимость в валюте по КП (цена поставщика + пошлина) × кол-во."
    )
    quoted_rate = serializers.CharField(allow_null=True, help_text="Курс КП (снимок или договорной).")
    quoted_rate_date = serializers.CharField(allow_null=True)
    quoted_cost = serializers.CharField(help_text="Себестоимость в UZS по КП.")
    has_actual = serializers.BooleanField()
    actual_amount = serializers.CharField(allow_null=True, help_text="Фактическая сумма в валюте; null — как в КП.")
    actual_rate = serializers.CharField(allow_null=True)
    actual_cost = serializers.CharField(help_text="Себестоимость в UZS по факту (нет факта — как в КП).")
    cost_deviation = serializers.CharField(help_text="actual_cost − quoted_cost, UZS.")
    purchased_on = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_blank=True)
    entered_by_name = serializers.CharField(allow_blank=True)
    suggested_rate = serializers.CharField(allow_null=True, help_text="Курс справочника на сегодня — подсказка.")
    suggested_rate_date = serializers.CharField(allow_null=True)


class MarginDeviationSerializer(serializers.Serializer):
    """Отклонение маржи сделки: опорное КП, построчно по валютам, итог. Суммы — строки, UZS."""

    deal = serializers.IntegerField()
    currency = serializers.CharField(help_text="Валюта всех сумм — UZS.")
    reference_quote = ReferenceQuoteSerializer(allow_null=True)
    rows = MarginDeviationRowSerializer(many=True)
    has_actuals = serializers.BooleanField()
    revenue = serializers.CharField(required=False, help_text="Сумма позиций КП без НДС.")
    quoted_cost = serializers.CharField(required=False)
    quoted_profit = serializers.CharField(required=False)
    quoted_margin_percent = serializers.CharField(required=False)
    actual_cost = serializers.CharField(required=False)
    actual_profit = serializers.CharField(required=False)
    actual_margin_percent = serializers.CharField(required=False)
    deviation_amount = serializers.CharField(required=False, help_text="Прибыль по факту − прибыль по КП, UZS.")
    deviation_percent_points = serializers.CharField(required=False, help_text="Маржа по факту − маржа по КП, п. п.")
    deviation_profit_percent = serializers.CharField(
        required=False, allow_null=True, help_text="Отклонение в % к прибыли КП; null — прибыль КП 0."
    )
