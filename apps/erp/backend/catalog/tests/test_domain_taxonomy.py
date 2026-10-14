"""Domain constraints + taxonomy-dedupe migration tests.

Moved out of the legacy catalog/tests.py file, which collided with the
catalog/tests/ package (both resolve to module `catalog.tests`, breaking pytest
collection on a clean checkout). Content is unchanged.
"""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from catalog.models import Category, DomainType, Product


class DomainConstraintsTest(TestCase):
    def setUp(self):
        # RAILWAY_MACHINERY / SERVICES are seeded by a data migration (Rule 1), so use
        # get_or_create — a plain create() collides with the seeded row (UniqueViolation).
        self.railway_domain = DomainType.objects.get_or_create(
            code="RAILWAY_MACHINERY", defaults={"name": "Railway Machinery", "sku_prefix": "RM"}
        )[0]
        self.services_domain = DomainType.objects.get_or_create(
            code="SERVICES", defaults={"name": "Services", "sku_prefix": "SV"}
        )[0]

    def test_railway_machinery_product_save(self):
        """
        Verify that creating a RAILWAY_MACHINERY product works without equipment groups (M1-ERP-02 wave 4).
        """
        product = Product.objects.create(name="Test Railway Product", domain_type=self.railway_domain)
        self.assertEqual(product.domain_type.code, "RAILWAY_MACHINERY")

    def test_services_product(self):
        product = Product.objects.create(name="Test Service", domain_type=self.services_domain)
        self.assertEqual(product.domain_type.code, "SERVICES")


class TaxonomyDedupeTest(TestCase):
    """catalog/0008: merge duplicate Category/EquipmentGroup by name, keep lowest id,
    re-parent children (parent is CASCADE!), remap products, fix the typo."""

    def setUp(self):
        self.mig = importlib.import_module("catalog.migrations.0008_dedupe_taxonomy")

    def test_merges_duplicate_categories_and_reparents_children(self):
        canon = Category.objects.create(name="ЖД Техника")
        dup = Category.objects.create(name="ЖД Техника")  # duplicate, higher id
        child = Category.objects.create(name="Краны", parent=dup)  # under the dup
        product = Product.objects.create(name="Рельс Р65", category=dup)

        self.mig.dedupe_taxonomy(django_apps, None)

        # the duplicate is gone, the canonical survives
        self.assertFalse(Category.objects.filter(id=dup.id).exists())
        self.assertTrue(Category.objects.filter(id=canon.id).exists())
        # the child was re-parented (NOT cascade-deleted) onto the canonical
        child.refresh_from_db()
        self.assertEqual(child.parent_id, canon.id)
        # the product followed onto the canonical
        product.refresh_from_db()
        self.assertEqual(product.category_id, canon.id)

    def test_fixes_typo_and_folds_into_correct_spelling(self):
        correct = Category.objects.create(name="Безопасность")
        Category.objects.create(name="Безопастность")  # typo
        self.mig.dedupe_taxonomy(django_apps, None)
        self.assertEqual(Category.objects.filter(name__in=["Безопасность", "Безопастность"]).count(), 1)
        self.assertTrue(Category.objects.filter(id=correct.id, name="Безопасность").exists())
