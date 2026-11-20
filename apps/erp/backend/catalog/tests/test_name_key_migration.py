"""СЦ-10: миграция 0018 заполняет ключ имени у карточек, созданных до неё."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("catalog", "0017_brand_names")]
AFTER = [("catalog", "0018_product_name_key")]


@pytest.mark.django_db(transaction=True)
def test_0018_fills_the_name_key_of_existing_cards():
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    Status = old.get_model("catalog", "ProductStatus")
    draft, _ = Status.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    card = old.get_model("catalog", "Product").objects.create(name="Рельс  P65, ГОСТ", sku="RT-MIG00018", status=draft)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(AFTER)
    new = executor.loader.project_state(AFTER).apps

    assert new.get_model("catalog", "Product").objects.get(pk=card.pk).name_key == "рельс р65 гост"

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
