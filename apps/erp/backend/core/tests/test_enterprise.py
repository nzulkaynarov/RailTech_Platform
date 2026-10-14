"""
Enterprise Automated Test Suite for ERP Ecosystem.

Covers the three most critical areas:
1. Financial engine accuracy (Landed Cost pipeline)
2. Security: RBAC data isolation
3. Smart Match domain routing
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Company, CustomUser
from crm.models import Deal, Quote, QuoteItem
from sourcing.tasks import route_domain


def make_user(username, is_staff=False, company=None, is_superuser=False):
    user = CustomUser.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@test.com",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    if company:
        from accounts.models import CompanyMember, WorkspaceRole

        role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner"})
        CompanyMember.objects.create(user=user, company=company, role=role, is_primary=True)
    return user


def make_company():
    return Company.objects.create(
        name="Test Company",
        inn="123456789",
    )


class LandedCostPipelineTest(TestCase):
    """Tests the enterprise financial engine: FCA → DAP → Margin → VAT."""

    def setUp(self):
        self.company = make_company()
        self.client_user = make_user("client1", company=self.company)
        self.deal = Deal.objects.create(client=self.client_user, company=self.company)
        self.quote = Quote.objects.create(deal=self.deal, vat_rate=Decimal("12.00"))

    def test_landed_cost_calculation_saves_to_db(self):
        """
        Verifies that QuoteItem.save() triggers financial engine to store
        Landed Cost as a real DB field (not a computed property).
        """
        item = QuoteItem.objects.create(
            quote=self.quote,
            frozen_base_price=Decimal("1000.00"),
            logistics_cost=Decimal("200.00"),
            customs_duty=Decimal("50.00"),
            margin_percent=Decimal("15.00"),
            quantity=1,
        )
        # F3.8: freight is now a DOCUMENT-level charge, not a per-line cost — logistics_cost is
        # hard-zeroed by the engine. Customs stays per-line (driven by the line's ТНВЭД).
        # landed_cost = base + customs = 1000 + 50 = 1050 (the 200 logistics is ignored).
        self.assertEqual(item.logistics_cost, Decimal("0.00"))
        self.assertEqual(item.landed_cost, Decimal("1050.00"))
        # final_price_excl_vat = 1050 * 1.15 = 1207.50
        self.assertEqual(item.final_price_excl_vat, Decimal("1207.50"))

    def test_zero_margin_is_valid(self):
        """Edge case: margin of 0% must not break the pipeline."""
        item = QuoteItem.objects.create(
            quote=self.quote,
            frozen_base_price=Decimal("500.00"),
            logistics_cost=Decimal("100.00"),
            customs_duty=Decimal("0.00"),
            margin_percent=Decimal("0.00"),
            quantity=1,
        )
        # F3.8: logistics zeroed → landed = base only = 500 (customs is 0 here).
        self.assertEqual(item.landed_cost, Decimal("500.00"))
        self.assertEqual(item.final_price_excl_vat, Decimal("500.00"))


class RBACSecurityTest(TestCase):
    """Tests that clients cannot access each other's deals (data isolation)."""

    def setUp(self):
        company_a = make_company()
        Company.objects.create(name="Company B", inn="987654321")
        self.client_a = make_user("client_a", company=company_a)
        self.client_b = make_user("client_b")
        # Only a Platform Admin sees every company's deals (DealViewSet.get_queryset
        # checks is_superuser, which is_superuser satisfies). A plain is_staff
        # user is not a platform admin under the ADR-0002 role model.
        self.manager = make_user("manager1", is_superuser=True)

        self.deal_a = Deal.objects.create(client=self.client_a, company=company_a)
        self.api_client = APIClient()

    def test_unauthenticated_user_cannot_access_deals(self):
        """Unauthenticated requests must return 401."""
        response = self.api_client.get("/api/v1/crm/deals/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_client_b_cannot_see_client_a_deal(self):
        """Client B must not see Deal belonging to Client A (returns empty list)."""
        self.api_client.force_authenticate(user=self.client_b)
        response = self.api_client.get("/api/v1/crm/deals/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deal_ids = [d["id"] for d in response.data["results"]]
        self.assertNotIn(self.deal_a.id, deal_ids)

    def test_manager_sees_all_deals(self):
        """Staff user must see all deals in the system."""
        self.api_client.force_authenticate(user=self.manager)
        response = self.api_client.get("/api/v1/crm/deals/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deal_ids = [d["id"] for d in response.data["results"]]
        self.assertIn(self.deal_a.id, deal_ids)


class SmartMatchDomainRouterTest(TestCase):
    """Tests the domain routing logic used during Excel import."""

    def test_routes_railway_keywords(self):
        self.assertEqual(route_domain("Колесная пара для ТЭМ18"), "GENERAL_GOODS")
        self.assertEqual(route_domain("Тяговый двигатель вл80"), "GENERAL_GOODS")

    def test_routes_service_keywords(self):
        self.assertEqual(route_domain("Услуга по монтажу"), "GENERAL_GOODS")
        self.assertEqual(route_domain("Delivery from Moscow"), "GENERAL_GOODS")

    def test_fallback_to_general_goods(self):
        self.assertEqual(route_domain("Болт М6 оцинкованный"), "GENERAL_GOODS")
        self.assertEqual(route_domain("Краска акриловая серая"), "GENERAL_GOODS")
