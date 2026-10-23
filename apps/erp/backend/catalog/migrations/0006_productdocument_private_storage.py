"""Документы товаров — в приватный бакет `erp-private` (S0-9): раньше лежали в публичном `erp-public`.

Схема: поле файла получает `get_private_storage`. Данные: уже загруженные файлы переносятся из `erp-public` в
`erp-private` под тем же ключом и удаляются из публичного бакета (повторный запуск безопасен: что уже перенесено —
пропускается). Без S3 (DEBUG, тесты: оба хранилища — одна файловая система) переносить нечего.
"""

import logging

import core.storage
from django.db import migrations, models

logger = logging.getLogger(__name__)


def move_documents_to_private(apps, schema_editor):
    public, private = core.storage.get_public_storage(), core.storage.get_private_storage()
    if public is private or public.bucket_name == private.bucket_name:
        return
    ProductDocument = apps.get_model("catalog", "ProductDocument")
    for name in ProductDocument.objects.exclude(file="").exclude(file__isnull=True).values_list("file", flat=True):
        if private.exists(name):
            if public.exists(name):
                public.delete(name)
            continue
        try:
            with public.open(name, "rb") as source:
                saved = private.save(name, source)
        except FileNotFoundError:
            logger.warning("product document %s is missing in the public bucket; skipped", name)
            continue
        if saved != name:  # ключ с UUID не занят, но на всякий случай не теряем файл, если хранилище выбрало другое имя
            raise RuntimeError(f"private storage renamed {name} to {saved}")
        public.delete(name)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_category_parent_protect"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productdocument",
            name="file",
            field=models.FileField(
                blank=True,
                help_text="Загруженный документ (PDF, DOCX)",
                null=True,
                storage=core.storage.get_private_storage,
                upload_to=core.storage.product_document_path,
                verbose_name="Файл",
            ),
        ),
        migrations.RunPython(move_documents_to_private, migrations.RunPython.noop),
    ]
