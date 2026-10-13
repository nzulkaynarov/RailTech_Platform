"""Company КП-defaults + numbering settings: OWNER-gated, tenant-scoped round-trip."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanySettings, CustomUser, WorkspaceRole
from master_data.models import Currency, DeliveryBasis

pytestmark = pytest.mark.django_db


def _owner(email, company):
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Владелец", "sort_order": 1})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=owner_role, is_primary=True, is_active=True)
    return user


@pytest.fixture
def company_a():
    return Company.objects.create(name="ACME LLC", inn="3000000001")


@pytest.fixture
def company_b():
    return Company.objects.create(name="BETA LLC", inn="3000000002")


@pytest.fixture
def lookups():
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "sort_order": 1})[0]
    fca = DeliveryBasis.objects.get_or_create(code="FCA", defaults={"name": "FCA", "sort_order": 1})[0]
    return usd, fca


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_owner_round_trips_own_company_settings(company_a, lookups):
    owner = _owner("owner.a@example.com", company_a)
    client = _client(owner)
    url = f"/api/v1/accounts/companies/{company_a.id}/settings/"

    resp = client.patch(
        url,
        {
            "default_cost_currency": "USD",
            "default_delivery_basis": "FCA",
            "default_vat_rate": "12.00",
            "default_margin_percent": "15.50",
            "default_offer_validity_days": 30,
            "doc_number_prefix": "ACME",
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["default_cost_currency_code"] == "USD"
    assert resp.data["default_delivery_basis_code"] == "FCA"
    assert resp.data["doc_number_prefix"] == "ACME"

    got = client.get(url)
    assert got.status_code == 200
    assert got.data["default_margin_percent"] == "15.50"
    assert got.data["default_offer_validity_days"] == 30

    row = CompanySettings.objects.get(company=company_a)
    assert row.default_cost_currency.code == "USD"
    assert row.doc_number_prefix == "ACME"


def test_other_owner_cannot_touch_foreign_company_settings(company_a, company_b):
    owner_b = _owner("owner.b@example.com", company_b)
    client = _client(owner_b)
    url = f"/api/v1/accounts/companies/{company_a.id}/settings/"
    # Foreign company is not in owner_b's IsPlatformAdmin-or-member queryset → 404/403.
    resp = client.patch(url, {"doc_number_prefix": "HACK"}, format="json")
    assert resp.status_code in (403, 404)
    assert not CompanySettings.objects.filter(company=company_a, doc_number_prefix="HACK").exists()


def test_non_owner_member_forbidden(company_a):
    sales_role = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 2}
    )[0]
    member = CustomUser.objects.create_user(
        email="sales.a@example.com", username="sales.a@example.com", password="pw", is_active=True
    )
    CompanyMember.objects.create(user=member, company=company_a, role=sales_role, is_primary=True, is_active=True)
    client = _client(member)
    url = f"/api/v1/accounts/companies/{company_a.id}/settings/"
    resp = client.patch(url, {"doc_number_prefix": "NOPE"}, format="json")
    assert resp.status_code == 403


def test_bad_currency_code_rejected(company_a):
    owner = _owner("owner.bad@example.com", company_a)
    client = _client(owner)
    url = f"/api/v1/accounts/companies/{company_a.id}/settings/"
    resp = client.patch(url, {"default_cost_currency": "ZZZ"}, format="json")
    assert resp.status_code == 400
    assert resp.data["detail"] == "BAD_CURRENCY"
