"""Ссылка на позицию каталога в строке любого документа (план ЕД-4, `ui-standard.md` §12).

Одна форма во всех строках — расчёт, КП, заказ поставщику, склад: `{id, name, sku, kind, photo}`. `photo` — id главного
фото или `None`; по нему клиент берёт миниатюру (`catalog/items/{id}/thumbnail/`) и сбрасывает кэш, когда фото меняется.
Название — название карточки; слова клиента строки остаются в самой строке (ADR-0027 п. 4).
"""

from __future__ import annotations

from collections.abc import Iterable

from rest_framework import serializers


def main_photos(product_ids: Iterable[int | None]) -> dict[int, int]:
    """Главное фото каждой позиции одним запросом: `{product_id: image_id}`."""
    from catalog.models import ProductImage

    ids = {pk for pk in product_ids if pk}
    if not ids:
        return {}
    rows = ProductImage.objects.filter(product_id__in=ids, is_main=True).exclude(image="")
    return dict(rows.values_list("product_id", "id"))


def item_ref(product, photos: dict[int, int] | None = None) -> dict | None:
    """Ссылка на позицию; `photos` — результат `main_photos` для строк страницы, без него фото ищется запросом."""
    if product is None:
        return None
    if photos is None:
        photos = main_photos([product.pk])
    return {
        "id": product.pk,
        "name": product.name,
        "sku": product.sku or "",
        "kind": "service" if product.is_service else "goods",
        "photo": photos.get(product.pk),
    }


class ItemRefSerializer(serializers.Serializer):
    """Схема ссылки на позицию в выгрузке (`erp-internal.yaml`): одна на все строки."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    sku = serializers.CharField(allow_blank=True, help_text="Наш артикул")
    kind = serializers.ChoiceField(choices=["goods", "service"])
    photo = serializers.IntegerField(
        allow_null=True, help_text="Id главного фото; миниатюра — catalog/items/{id}/thumbnail/, null — значок типа"
    )
