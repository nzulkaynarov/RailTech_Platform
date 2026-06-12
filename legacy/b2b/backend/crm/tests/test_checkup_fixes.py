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

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
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
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    VerificationStatus.objects.get_or_create(code="L1_UNVERIFIED", defaults={"name": "L1", "sort_order": 10})


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def buyer(lookups):
    company = Company.objects.create(
        name="Buyer LLC",
        inn="3300000001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
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
    """Buyers can fetch the verified-supplier directory to invite to an RFQ —
    unverified sellers are excluded, and only id/name/inn are returned."""
    user, _ = buyer
    verified = Company.objects.create(
        name="Verified Supplier",
        inn="7700000010",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    verified.types.add(CompanyType.objects.get(code="SUPPLIER"))
    unverified = Company.objects.create(
        name="Unverified Supplier",
        inn="7700000011",
        verification_status=VerificationStatus.objects.get(code="L1_UNVERIFIED"),
    )
    unverified.types.add(CompanyType.objects.get(code="SUPPLIER"))

    resp = _api(user).get("/api/v1/accounts/companies/suppliers/")
    assert resp.status_code == 200
    names = {row["name"] for row in resp.data}
    assert "Verified Supplier" in names
    assert "Unverified Supplier" not in names
    assert set(resp.data[0].keys()) == {"id", "name", "inn"}


def test_full_company_list_stays_admin_only(buyer):
    """The dedicated suppliers action must NOT have opened the admin company list."""
    user, _ = buyer
    resp = _api(user).get("/api/v1/accounts/companies/")
    assert resp.status_code == 403


# ── is_verified ↔ verification_status sync (checkup #5) ─────────────────────


def test_kyc_verification_syncs_is_verified(buyer):
    """verify_company_kyc keeps the denormalised is_verified flag consistent so
    /me/ can't show is_verified=False next to L2_VERIFIED."""
    from accounts.services.kyc import verify_company_kyc

    user, company = buyer
    company.is_verified = False  # simulate the drift the checkup found
    company.save(update_fields=["is_verified"])

    verify_company_kyc(company, user, level_code="L2_VERIFIED", require_documents=False)
    company.refresh_from_db()
    assert company.is_verified is True


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
