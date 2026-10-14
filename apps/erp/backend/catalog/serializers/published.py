"""Сериализатор опубликованного слоя (M1-ERP-07) — тонкая обёртка над `published_projection`.

Поля объявлены ради схемы OpenAPI (совпадают с `CatalogItem` портального контракта); значения
отдаёт ОДНА функция проекции, поэтому сериализатор не может «случайно» добавить поле внутреннего
слоя: `to_representation` его не читает.
"""

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..models import FulfillmentPolicy, ProductKind


class _MoneySerializer(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class _AttributeSerializer(serializers.Serializer):
    name = serializers.CharField()
    value = serializers.CharField()


class _DocumentLinkSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.URLField()


@extend_schema_serializer(component_name="PublishedCatalogItem")
class PublishedCatalogItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=ProductKind.choices)
    name = serializers.CharField()
    description = serializers.CharField()
    unit = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    fulfillment_policy = serializers.ChoiceField(choices=FulfillmentPolicy.choices, allow_null=True)
    price = _MoneySerializer(allow_null=True, help_text="`null` — «цена по запросу»")
    availability = serializers.ChoiceField(
        choices=[("in_stock", "in_stock"), ("on_order", "on_order"), ("expected", "expected")], allow_null=True
    )
    lead_time_days = serializers.IntegerField(allow_null=True)
    images = serializers.ListField(child=serializers.URLField())
    documents = _DocumentLinkSerializer(many=True)
    attributes = _AttributeSerializer(many=True)

    def to_representation(self, instance):
        from catalog.services.layers import published_projection

        return published_projection(instance, request=self.context.get("request"))
