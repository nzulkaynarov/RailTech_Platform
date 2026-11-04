"""Миграция catalog/0011 на данных (CAT-CARD-1): виды документов, перенос `ProductDocument` в `TechDocument`, порядок фото.

Настоящий прогон: `MigrationExecutor` откатывает `catalog` к 0009, данные пишутся историческими моделями, затем
0010 и 0011 применяются, потом откат и повторное применение (дубликатов нет). Всё в транзакции теста.
"""

from __future__ import annotations

import importlib

import pytest
from django.core.files.base import ContentFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

BEFORE = [("catalog", "0009_category_tracking")]
AFTER = [("catalog", "0011_cat_card_data")]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _migrate(targets):
    with (
        connection.cursor() as cursor
    ):  # отложенные проверки внешних ключей данных теста — сейчас, иначе ALTER TABLE не пустят
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def old():
    state = _migrate(BEFORE)
    yield state
    _migrate(AFTER)  # дерево остаётся на листе: следующие тесты ждут новую схему


def _product(apps, name, sku):
    return apps.get_model("catalog", "Product").objects.create(name=name, sku=sku)


def _legacy_doc(apps, product, name, filename):
    doc = apps.get_model("catalog", "ProductDocument")(product=product, name=name)
    doc.file.save(filename, ContentFile(PDF), save=False)
    doc.save()
    return doc


def test_kinds_documents_and_photos_are_migrated(old):
    product = _product(old, "Реле", "MIG-1")
    other = _product(old, "Кабель", "MIG-2")
    _legacy_doc(old, product, "Сертификат ГОСТ", "cert.pdf")
    _legacy_doc(old, product, "Паспорт изделия", "passport.pdf")
    _legacy_doc(old, other, "Схема подключения", "scheme.pdf")
    linkonly = old.get_model("catalog", "ProductDocument").objects.create(
        product=product, name="Каталог на сайте", file_url="https://example.com/c.pdf"
    )
    Tech = old.get_model("catalog", "TechDocument")
    legacy_tech = Tech.objects.create(kind="certificate", title="Старый реестр", original_name="x.pdf", product=product)
    Image = old.get_model("catalog", "ProductImage")
    # у товара две «главные», порядок с дырами; у соседа главной нет
    a = Image.objects.create(product=product, is_main=False, sort_order=7)
    b = Image.objects.create(product=product, is_main=True, sort_order=3)
    c = Image.objects.create(product=product, is_main=True, sort_order=5)
    d = Image.objects.create(product=other, is_main=False, sort_order=4)
    e = Image.objects.create(product=other, is_main=False, sort_order=9)

    new = _migrate(AFTER)

    codes = set(new.get_model("catalog", "DocumentKind").objects.values_list("code", flat=True))
    assert codes == {
        "certificate",
        "declaration",
        "passport",
        "manual",
        "warranty_card",
        "tz",
        "drawing",
        "pnr",
        "other",
    }
    kind = new.get_model("catalog", "DocumentKind").objects.get(code="certificate")
    assert kind.has_validity and kind.client_visible_default

    docs = new.get_model("catalog", "TechDocument").objects
    moved = {d.title: d for d in docs.filter(product_id=product.pk).exclude(pk=legacy_tech.pk)}
    assert set(moved) == {"Сертификат ГОСТ", "Паспорт изделия"}  # ссылка без файла не переносится
    assert moved["Сертификат ГОСТ"].kind == "certificate" and moved["Паспорт изделия"].kind == "passport"
    assert all(m.client_visible and m.original_name and m.size_bytes == len(PDF) for m in moved.values())
    assert docs.get(product_id=other.pk).kind == "other"
    # файл скопирован под новым ключом: старый остаётся нетронутым
    old_doc = new.get_model("catalog", "ProductDocument").objects.get(name="Сертификат ГОСТ")
    assert moved["Сертификат ГОСТ"].file.name != old_doc.file.name and old_doc.file.storage.exists(old_doc.file.name)
    assert moved["Сертификат ГОСТ"].file.storage.exists(moved["Сертификат ГОСТ"].file.name)
    assert docs.get(pk=legacy_tech.pk).kind == "certificate" and docs.get(pk=legacy_tech.pk).client_visible is False
    assert linkonly.pk and docs.count() == 4

    images = new.get_model("catalog", "ProductImage").objects
    assert [(i.pk, i.sort_order, i.is_main) for i in images.filter(product_id=product.pk).order_by("sort_order")] == [
        (b.pk, 0, True),
        (c.pk, 1, False),
        (a.pk, 2, False),
    ]
    assert [(i.pk, i.sort_order, i.is_main) for i in images.filter(product_id=other.pk).order_by("sort_order")] == [
        (d.pk, 0, True),
        (e.pk, 1, False),
    ]


def test_the_migration_is_reversible_and_does_not_duplicate_on_replay(old):
    product = _product(old, "Реле", "MIG-3")
    _legacy_doc(old, product, "Инструкция по монтажу", "manual.pdf")
    _migrate(AFTER)
    back = _migrate(BEFORE)
    assert back.get_model("catalog", "TechDocument").objects.count() == 1  # данные при откате схемы остаются
    again = _migrate(AFTER)
    assert again.get_model("catalog", "TechDocument").objects.filter(product_id=product.pk).count() == 1
    assert again.get_model("catalog", "DocumentKind").objects.count() == 9
    forwards = importlib.import_module("catalog.migrations.0011_cat_card_data").forwards
    forwards(again, None)  # второй вызов на тех же данных
    assert again.get_model("catalog", "TechDocument").objects.filter(product_id=product.pk).count() == 1


def test_kind_hints_pick_the_document_kind_from_the_old_name():
    kind_for = importlib.import_module("catalog.migrations.0011_cat_card_data").kind_for
    assert [
        kind_for(n) for n in ("Сертификат", "Декларация", "ПАСПОРТ", "Инструкция", "Гарантийный талон", "Фото")
    ] == [
        "certificate",
        "declaration",
        "passport",
        "manual",
        "warranty_card",
        "other",
    ]
