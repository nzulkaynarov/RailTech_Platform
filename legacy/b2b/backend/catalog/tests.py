from django.test import TestCase

from catalog.models import DomainType, EquipmentGroup, Product


class DomainConstraintsTest(TestCase):
    def setUp(self):
        self.railway_domain = DomainType.objects.create(
            name="Railway Machinery", code="RAILWAY_MACHINERY", sku_prefix="RM"
        )
        self.services_domain = DomainType.objects.create(name="Services", code="SERVICES", sku_prefix="SV")

    def test_railway_machinery_product_save(self):
        """
        Verify that creating a RAILWAY_MACHINERY product and assigning M2M works.
        """
        group = EquipmentGroup.objects.create(name="Test Group")
        product = Product.objects.create(name="Test Railway Product", domain_type=self.railway_domain)
        product.equipment_groups.add(group)
        self.assertEqual(product.equipment_groups.count(), 1)
        self.assertEqual(product.domain_type.code, "RAILWAY_MACHINERY")

    def test_services_product(self):
        product = Product.objects.create(name="Test Service", domain_type=self.services_domain)
        self.assertEqual(product.equipment_groups.count(), 0)
