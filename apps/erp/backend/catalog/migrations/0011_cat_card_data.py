"""Данные карточки товара (CAT-CARD-1): виды документов, перенос документов товара в единый реестр, порядок фото.

1. Справочник `DocumentKind` — девять видов (`get_or_create`: правки администратора на стендах не затираются); коды старых
   видов tz / drawing / certificate / pnr / other остаются теми же, поэтому существующие `TechDocument` уже на записях справочника.
2. `ProductDocument` (паспорт в карточке для старого фронта) копируется в `TechDocument` с «видно клиенту = да» (решение
   2026-11-03: один реестр документов товара). Файл копируется в приватном хранилище под новым ключом — удаление через старый
   интерфейс не ломает новую запись. Запись без файла (только ссылка) не переносится. Повторный запуск не дублирует.
   Старая модель и её эндпоинты живут до P6.
3. Фото товара получают порядок 0..n-1 и ровно одно главное (главное остаётся первым).

Откат данных — пустой (CONVENTIONS ERP §5): созданное остаётся, откат схемы убирает таблицу видов.
"""

import logging
import mimetypes
import os

from django.core.files import File
from django.db import migrations

logger = logging.getLogger(__name__)

#: (код, название, имеет срок, видно клиенту по умолчанию, порядок)
KINDS = [
    ("certificate", "Сертификат соответствия", True, True, 10),
    ("declaration", "Декларация о соответствии", True, True, 20),
    ("passport", "Паспорт изделия", False, True, 30),
    ("manual", "Инструкция", False, True, 40),
    ("warranty_card", "Гарантийный талон", False, True, 50),
    ("tz", "Техническое задание", False, False, 60),
    ("drawing", "Чертёж", False, False, 70),
    ("pnr", "Регламент ПНР", False, False, 80),
    ("other", "Прочее", False, False, 90),
]

#: Подстрока названия старого документа (в нижнем регистре) -> код вида.
NAME_HINTS = [
    ("сертификат", "certificate"),
    ("деклараци", "declaration"),
    ("паспорт", "passport"),
    ("инструкц", "manual"),
    ("гарант", "warranty_card"),
]


def seed_kinds(apps):
    DocumentKind = apps.get_model("catalog", "DocumentKind")
    for code, name, has_validity, visible, order in KINDS:
        DocumentKind.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "has_validity": has_validity,
                "client_visible_default": visible,
                "sort_order": order,
            },
        )


def kind_for(name: str) -> str:
    lowered = (name or "").lower()
    for hint, code in NAME_HINTS:
        if hint in lowered:
            return code
    return "other"


def move_product_documents(apps):
    ProductDocument = apps.get_model("catalog", "ProductDocument")
    TechDocument = apps.get_model("catalog", "TechDocument")
    for old in ProductDocument.objects.order_by("id"):
        if not old.file:
            logger.warning("product document %s has no uploaded file (link only); not moved", old.pk)
            continue
        original = os.path.basename(old.file.name)[:255]
        title = (old.name or original)[:255]
        if TechDocument.objects.filter(product_id=old.product_id, title=title, original_name=original).exists():
            continue
        try:
            with old.file.open("rb") as handle:
                copy = TechDocument(
                    kind=kind_for(old.name),
                    title=title,
                    original_name=original,
                    content_type=mimetypes.guess_type(original)[0] or "application/octet-stream",
                    size_bytes=old.file.size,
                    product_id=old.product_id,
                    client_visible=True,
                )
                copy.file.save(original, File(handle), save=False)
        except FileNotFoundError:
            logger.warning("product document %s: file %s is missing in the storage; not moved", old.pk, old.file.name)
            continue
        copy.save()
        TechDocument.objects.filter(pk=copy.pk).update(created_at=old.uploaded_at)


def normalise_images(apps):
    ProductImage = apps.get_model("catalog", "ProductImage")
    by_product: dict[int, list] = {}
    for image in ProductImage.objects.order_by("product_id", "-is_main", "sort_order", "id"):
        by_product.setdefault(image.product_id, []).append(image)
    for images in by_product.values():
        for position, image in enumerate(images):
            is_main = position == 0
            if image.sort_order != position or image.is_main != is_main:
                ProductImage.objects.filter(pk=image.pk).update(sort_order=position, is_main=is_main)


def forwards(apps, schema_editor):
    seed_kinds(apps)
    move_product_documents(apps)
    normalise_images(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0010_cat_card_schema"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
