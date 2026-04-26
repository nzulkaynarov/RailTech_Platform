from django.core.cache import cache
from django.test import TestCase

from sourcing.tasks import route_domain


class DomainRouterTest(TestCase):
    def setUp(self):
        from catalog.models import DomainType
        from sourcing.models import DomainKeyword

        cache.clear()
        railway = DomainType.objects.create(name="Railway Machinery", code="RAILWAY_MACHINERY", sku_prefix="RM")
        services = DomainType.objects.create(name="Services", code="SERVICES", sku_prefix="SV")
        DomainKeyword.objects.create(keyword="вл80", domain_type=railway)
        DomainKeyword.objects.create(keyword="тепловоз", domain_type=railway)
        DomainKeyword.objects.create(keyword="тяговый", domain_type=railway)
        DomainKeyword.objects.create(keyword="доставка", domain_type=services)
        DomainKeyword.objects.create(keyword="ремонт", domain_type=services)

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
