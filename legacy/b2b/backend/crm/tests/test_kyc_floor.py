"""ADR-0006 Phase E — the backend KYC floor. Submitting a заявка requires an L2-verified company;
below L2 a buyer can build a draft but not submit («после KYC = минимум»)."""

import pytest
from rest_framework.exceptions import PermissionDenied

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from accounts.services.kyc import company_kyc_verified
from crm.models import Deal, DealStage
from crm.services.rfq import submit_request


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "RFQ_OPEN"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 1})
    for code, rank in [("L1_UNVERIFIED", 0), ("L2_VERIFIED", 2)]:
        VerificationStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": rank})
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 50})


def _buyer_on(company):
    user = CustomUser.objects.create_user(
        email=f"b{company.id}@t.test", username=f"b{company.id}@t.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        is_active=True,
        can_buy=True,
        is_primary=True,
    )
    return user


def _company(status_code):
    c = Company.objects.create(
        name=f"Co-{status_code}", verification_status=VerificationStatus.objects.get(code=status_code)
    )
    c.types.add(CompanyType.objects.get(code="CLIENT"))
    return c


@pytest.mark.django_db
def test_company_kyc_verified_helper(lookups):
    assert company_kyc_verified(_company("L2_VERIFIED").id) is True
    assert company_kyc_verified(_company("L1_UNVERIFIED").id) is False


@pytest.mark.django_db
def test_submit_request_blocked_below_l2(lookups):
    company = _company("L1_UNVERIFIED")
    buyer = _buyer_on(company)
    deal = Deal.objects.create(title="d", company=company, stage=DealStage.objects.get(code="DRAFT"))
    with pytest.raises(PermissionDenied) as exc:
        submit_request(buyer, deal)
    assert "KYC_REQUIRED_TO_SUBMIT" in str(exc.value)
