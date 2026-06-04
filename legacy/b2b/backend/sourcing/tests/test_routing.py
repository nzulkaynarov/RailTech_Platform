from django.core.cache import cache
from django.test import TestCase

from sourcing.tasks import route_domain


class DomainRouterTest(TestCase):
    def setUp(self):
        from catalog.models import DomainType
        from sourcing.models import DomainKeyword

        cache.clear()
        # Idempotent: DomainTypes may already be seeded (data migration / fixture),
        # so get_or_create instead of create to keep the test environment-robust.
        railway, _ = DomainType.objects.get_or_create(
            code="RAILWAY_MACHINERY", defaults={"name": "Railway Machinery", "sku_prefix": "RM"}
        )
        services, _ = DomainType.objects.get_or_create(
            code="SERVICES", defaults={"name": "Services", "sku_prefix": "SV"}
        )
        for keyword in ("вл80", "тепловоз", "тяговый"):
            DomainKeyword.objects.get_or_create(keyword=keyword, domain_type=railway)
        for keyword in ("доставка", "ремонт"):
            DomainKeyword.objects.get_or_create(keyword=keyword, domain_type=services)

    def tearDown(self):
        cache.clear()

    def test_smart_match_nlp_routing(self):
        # 1. Test Railway Machinery keywords
        self.assertEqual(route_domain("Двигатель тяговый ВЛ80"), "RAILWAY_MACHINERY")
        self.assertEqual(route_domain("Электродвигатель тепловоза"), "RAILWAY_MACHINERY")

        # 2. Test Services keywords
        self.assertEqual(route_domain("Доставка оборудования"), "SERVICES")
        self.assertEqual(route_domain("Капитальный ремонт"), "SERVICES")

        # 3. Test General Goods fallback
        self.assertEqual(route_domain("Краска ПФ-115 20кг красная"), "GENERAL_GOODS")
        self.assertEqual(route_domain("Изолента ПВХ синяя"), "GENERAL_GOODS")
        self.assertEqual(route_domain("Гвозди строительные"), "GENERAL_GOODS")
