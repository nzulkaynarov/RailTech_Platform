"""Domain constraints + taxonomy-dedupe migration tests.

Moved out of the legacy catalog/tests.py file, which collided with the
catalog/tests/ package (both resolve to module `catalog.tests`, breaking pytest
collection on a clean checkout). Content is unchanged.
"""

from django.apps import apps as django_apps
from django.test import TestCase

from catalog.models import Category, DomainType, Product


class DomainConstraintsTest(TestCase):
    def setUp(self):
        self.goods_domain = DomainType.objects.get_or_create(
            code="GENERAL_GOODS", defaults={"name": "General Goods", "sku_prefix": "GD"}
        )[0]
        self.services_domain = DomainType.objects.get_or_create(
            code="SERVICES", defaults={"name": "Services", "sku_prefix": "SV"}
        )[0]

    def test_goods_product_save(self):
        """Verify that creating a GENERAL_GOODS product works."""
        product = Product.objects.create(name="Test Goods Product", domain_type=self.goods_domain)
        self.assertEqual(product.domain_type.code, "GENERAL_GOODS")

    def test_services_product(self):
        product = Product.objects.create(name="Test Service", domain_type=self.services_domain)
        self.assertEqual(product.domain_type.code, "SERVICES")


class TaxonomyDedupeTest(TestCase):
    """catalog/0008: merge duplicate Category/EquipmentGroup by name, keep lowest id,
    re-parent children (parent is CASCADE!), remap products, fix the typo."""

    def setUp(self):
        from types import SimpleNamespace

        from core.legacy_migration_helpers import dedupe_taxonomy

        self.mig = SimpleNamespace(dedupe_taxonomy=dedupe_taxonomy)

    def test_merges_duplicate_categories_and_reparents_children(self):
        canon = Category.objects.create(name="Тестовый металлопрокат")
        dup = Category.objects.create(name="Тестовый металлопрокат")  # duplicate, higher id
        child = Category.objects.create(name="Трубы", parent=dup)  # under the dup
        product = Product.objects.create(name="Труба стальная", category=dup)

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
