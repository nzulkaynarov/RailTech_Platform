"""WP-H — /me.capabilities early-gate signals for the КП builder.

The КП builder shows KYC / subscription blockers BEFORE the seller spends an hour on data
entry (the audit's "late surprise" at send). That needs two new capability fields mirroring
`send_to_client`'s gate order (SELLER_KYC_REQUIRED then QUOTE_SEND_NOT_ENTITLED):

  - can_send_quotes  = quote_send_entitled(company)  (KYC L2+ AND quote.send entitlement AND not DEMO)
  - quote_send_is_demo = the seller holds quote.send in DEMO access (watermarked, send-gated)

UI-gating only — send_to_client stays the authoritative gate. These tests pin the projection.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyEntitlement,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    VerificationStatus,
    WorkspaceRole,
)
from accounts.serializers import MeSerializer


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})


def _seller_user(email, *, with_subscription, operational=True, kyc=True):
    """A SUPPLIER-company OWNER with can_sell — mirrors crm.tests.test_subscription_gate."""
    company = Company.objects.create(
        name=f"Seller {email}",
        inn=email,
        verification_status=(VerificationStatus.objects.get(code="L2_VERIFIED") if kyc else None),
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
        can_buy=True,
    )
    if with_subscription:
        SupplierSubscription.objects.create(
            company=company,
            plan="PREMIUM",
            status="ACTIVE" if operational else "PAST_DUE",
            valid_until=timezone.now().date() + timedelta(days=30),
        )
    return user, company


def _caps(user):
    return MeSerializer(user).data["capabilities"]


def test_kyc_and_subscription_seller_can_send(lookups):
    user, _ = _seller_user("ok@wph.test", with_subscription=True, operational=True)
    caps = _caps(user)
    assert caps["can_send_quotes"] is True
    assert caps["quote_send_is_demo"] is False


def test_seller_without_kyc_cannot_send(lookups):
    user, _ = _seller_user("nokyc@wph.test", with_subscription=True, operational=True, kyc=False)
    caps = _caps(user)
    assert caps["can_send_quotes"] is False
    assert caps["quote_send_is_demo"] is False


def test_kyc_seller_without_subscription_cannot_send(lookups):
    user, _ = _seller_user("nosub@wph.test", with_subscription=False)
    caps = _caps(user)
    assert caps["can_send_quotes"] is False
    assert caps["quote_send_is_demo"] is False


def test_demo_entitlement_flags_watermark_and_blocks_send(lookups):
    user, company = _seller_user("demo@wph.test", with_subscription=True, operational=True)
    CompanyEntitlement.objects.create(company=company, feature_key="quote.send", access="DEMO")
    caps = _caps(user)
    # DEMO = build + watermark but never actually send → not entitled, but flagged as demo.
    assert caps["can_send_quotes"] is False
    assert caps["quote_send_is_demo"] is True


def test_buyer_only_user_has_no_seller_send_signals(lookups):
    company = Company.objects.create(name="Buyer co", inn="buyer@wph.test")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="buyer@wph.test", username="buyer@wph.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
        can_buy=True,
    )
    caps = _caps(user)
    assert caps["can_send_quotes"] is False
    assert caps["quote_send_is_demo"] is False
