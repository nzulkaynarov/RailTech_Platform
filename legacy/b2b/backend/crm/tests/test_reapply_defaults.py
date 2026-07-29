"""«Применить настройки компании» (Odoo Update Prices) — reapply_company_defaults + the
apply-defaults endpoint. Unlike the create-time fill-empties helper, this OVERWRITES the five
default-backed fields with the company's CURRENT CompanySettings, only touches fields that
actually differ, and never touches the locked presentation currency (UZS)/manual FX.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.constants import Permission
from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanySettings,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteStatus
from crm.services import reapply_company_defaults
from master_data.models import Country, Currency, DeliveryBasis

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    for code in ["DRAFT"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="CALCULATING", defaults={"name": "Calc", "sort_order": 40})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Sum", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "Dollar", "sort_order": 20})
    DeliveryBasis.objects.get_or_create(code="EXW", defaults={"name": "Ex Works", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})


@pytest.fixture
def seller_company(lookups):
    company = Company.objects.create(
        name="Seller LLC",
        inn="7700000101",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    company.types.add(
        CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    )
    SupplierSubscription.objects.create(
        company=company, plan="PREMIUM", status="ACTIVE", valid_until=timezone.now().date() + timedelta(days=365)
    )
    return company


@pytest.fixture
def configured_settings(seller_company):
    """Company defaults that DIFFER from the fresh-quote model defaults."""
    return CompanySettings.objects.create(
        company=seller_company,
        default_delivery_basis=DeliveryBasis.objects.get(code="EXW"),
        default_cost_currency=Currency.objects.get(code="USD"),
        default_vat_rate=Decimal("15.00"),
        default_margin_percent=Decimal("25.00"),
        default_offer_validity_days=30,
    )


@pytest.fixture
def draft_quote(seller_company):
    deal = Deal.objects.create(title="D", stage=DealStage.objects.get(code="CALCULATING"))
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company=seller_company,
        vat_rate=Decimal("12.00"),
        margin_percent=Decimal("0"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )


def test_reapply_overwrites_all_five_fields(draft_quote, seller_company, configured_settings):
    changed = reapply_company_defaults(draft_quote, seller_company)
    draft_quote.refresh_from_db()
    assert set(changed) == {"delivery_basis", "cost_currency_default", "vat_rate", "margin_percent", "valid_until"}
    assert draft_quote.vat_rate == Decimal("15.00")
    assert draft_quote.margin_percent == Decimal("25.00")
    assert draft_quote.delivery_basis.code == "EXW"
    assert draft_quote.cost_currency_default.code == "USD"
    assert draft_quote.valid_until == timezone.now().date() + timedelta(days=30)


def test_reapply_is_noop_when_already_current(draft_quote, seller_company, configured_settings):
    reapply_company_defaults(draft_quote, seller_company)
    # Second call: nothing differs from the company defaults now → empty changed list.
    changed = reapply_company_defaults(draft_quote, seller_company)
    assert changed == []


def test_reapply_never_touches_presentation_currency(draft_quote, seller_company, configured_settings):
    draft_quote.quote_currency = Currency.objects.get(code="UZS")
    draft_quote.save(update_fields=["quote_currency"])
    reapply_company_defaults(draft_quote, seller_company)
    draft_quote.refresh_from_db()
    assert draft_quote.quote_currency.code == "UZS"  # locked, never overwritten


def test_reapply_noop_without_settings(draft_quote, seller_company):
    # Company configured NO settings row → nothing to pull, safe no-op.
    changed = reapply_company_defaults(draft_quote, seller_company)
    assert changed == []


def _seller_user(company):
    user = CustomUser.objects.create_user(
        email="s@seller.test", username="s@seller.test", password="pw", is_active=True
    )
    role = CompanyRole.objects.create(
        company=company,
        name="Продажи",
        permissions=[Permission.QUOTE_BUILD.value, Permission.QUOTE_EDIT_PRICING.value],
    )
    workspace_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "OWNER", "sort_order": 10})[0]
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role,
        company_role=role,
        is_primary=True,
        is_active=True,
        can_sell=True,
    )
    return user


def test_endpoint_applies_defaults_for_seller(draft_quote, seller_company, configured_settings):
    user = _seller_user(seller_company)
    DealSellerRouting.objects.create(deal=draft_quote.deal, seller_company=seller_company, assigned_to=user)
    api = APIClient()
    api.force_authenticate(user=user)
    resp = api.post(f"/api/v1/crm/quotes/{draft_quote.id}/apply-defaults/", HTTP_X_ACTIVE_CONTEXT="seller")
    assert resp.status_code == 200, resp.content
    assert set(resp.json()["changed_fields"]) == {
        "delivery_basis",
        "cost_currency_default",
        "vat_rate",
        "margin_percent",
        "valid_until",
    }
    draft_quote.refresh_from_db()
    assert draft_quote.vat_rate == Decimal("15.00")


def test_endpoint_rejects_frozen_quote(draft_quote, seller_company, configured_settings):
    user = _seller_user(seller_company)
    DealSellerRouting.objects.create(deal=draft_quote.deal, seller_company=seller_company, assigned_to=user)
    draft_quote.frozen_at = timezone.now()
    draft_quote.save(update_fields=["frozen_at"])
    api = APIClient()
    api.force_authenticate(user=user)
    resp = api.post(f"/api/v1/crm/quotes/{draft_quote.id}/apply-defaults/", HTTP_X_ACTIVE_CONTEXT="seller")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "QUOTE_FROZEN"
