"""Карточкам без статуса проставляется статус — жизненный цикл перестаёт быть декоративным.

Замер 03-08: у 5 из 8 карточек `status` был NULL, то есть «черновик / опубликован / архив»
существовал только в справочнике. Волна B делает статус обязательным по смыслу: новая карточка
рождается черновиком (см. `Product.save`), а старым он проставляется здесь.

Правило бэкфилла берётся из ФАКТА, а не из догадки: карточка, по которой есть активное
предложение поставщика, уже участвует в торговле — значит она опубликована. Всё остальное —
черновик, который владелец дозаполнит в очереди наполнения.

Обратная операция — no-op: возвращать NULL значило бы вернуть дефект.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductStatus = apps.get_model("catalog", "ProductStatus")
    SupplierOffer = apps.get_model("catalog", "SupplierOffer")

    draft = ProductStatus.objects.filter(code="DRAFT").first()
    published = ProductStatus.objects.filter(code="PUBLISHED").first()
    if draft is None or published is None:  # pragma: no cover — справочник ставит миграция сидов
        return

    traded_ids = set(SupplierOffer.objects.filter(is_active=True).values_list("product_id", flat=True))
    for product in Product.objects.filter(status__isnull=True).iterator(chunk_size=500):
        product.status_id = published.pk if product.pk in traded_ids else draft.pk
        product.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [("catalog", "0013_product_candidate_provenance")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
