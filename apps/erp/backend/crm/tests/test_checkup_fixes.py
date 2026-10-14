"""DRF endpoint tests for the buyer/admin checkup fixes (2026-06-10).

Covers the regressions a service-only test (golden_path) could not catch because
it bypasses the view permission layer:
  * the supplier directory is member-accessible (buyers can browse suppliers)
    without exposing the admin-only full company list.
  * deal destroy is restricted to DRAFT for non-admins.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "RFQ_OPEN", "SOURCING", "CLOSED_LOST", "KYC_PENDING"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def buyer(lookups):
    company = Company.objects.create(
        name="Buyer LLC",
        inn="3300000001",
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(
        email="buyer@checkup.test", username="buyer_checkup", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
        can_buy=True,
    )
    return user, company


@pytest.fixture
def draft_deal(buyer):
    user, company = buyer
    return Deal.objects.create(
        title="Buyer Deal", company=company, client=user, stage=DealStage.objects.get(code="DRAFT")
    )


# ── supplier directory (checkup #1b) ────────────────────────────────────────


def test_supplier_directory_is_member_accessible(buyer):
    """Buyers can fetch the supplier directory to invite to an RFQ — active sellers only
    (archived ones are excluded), and only id/name/inn are returned. KYC verification was
    removed in M1-ERP-02 wave 1c, so it no longer narrows the directory."""
    user, _ = buyer
    active = Company.objects.create(
        name="Active Supplier",
        inn="7700000010",
    )
    active.types.add(CompanyType.objects.get(code="SUPPLIER"))
    archived = Company.objects.create(
        name="Archived Supplier",
        inn="7700000011",
        is_active=False,
    )
    archived.types.add(CompanyType.objects.get(code="SUPPLIER"))

    resp = _api(user).get("/api/v1/accounts/companies/suppliers/")
    assert resp.status_code == 200
    names = {row["name"] for row in resp.data}
    assert "Active Supplier" in names
    assert "Archived Supplier" not in names
    assert set(resp.data[0].keys()) == {"id", "name", "inn"}


def test_full_company_list_stays_admin_only(buyer):
    """The dedicated suppliers action must NOT have opened the admin company list."""
    user, _ = buyer
    resp = _api(user).get("/api/v1/accounts/companies/")
    assert resp.status_code == 403


# ── deal destroy guard (checkup #6) ─────────────────────────────────────────


def test_member_can_delete_draft_deal(buyer, draft_deal):
    user, _ = buyer
    resp = _api(user).delete(f"/api/v1/crm/deals/{draft_deal.id}/")
    assert resp.status_code == 204
    assert not Deal.objects.filter(pk=draft_deal.id).exists()


def test_member_cannot_delete_active_deal(buyer, draft_deal):
    user, _ = buyer
    draft_deal.stage = DealStage.objects.get(code="RFQ_OPEN")
    draft_deal.save(update_fields=["stage"])
    resp = _api(user).delete(f"/api/v1/crm/deals/{draft_deal.id}/")
    assert resp.status_code == 403
    assert Deal.objects.filter(pk=draft_deal.id).exists()
