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


# ──────────────────────────────────────────────────────────────────────────────
# `capabilities.can_sell` — «пользователь на стороне продавца» (аудит UI 2026-07-30)
# ──────────────────────────────────────────────────────────────────────────────
#
# Плоский флаг `can_sell` — это CompanyMember.can_sell, и он по умолчанию True у ЛЮБОГО
# участника. Пока `capabilities.can_sell` копировал его, SPA показывала продавцовские
# поверхности (мастер документов с КП/инвойсом, seller-секции настроек) члену чисто
# покупательской компании — и клик уводил в отказ. Теперь поле считает тот же предикат,
# что и авторизация: `is_seller` = активное членство с can_sell И компания-продавец.


def test_capability_can_sell_is_false_for_member_of_client_only_company(lookups):
    """Ключевой случай: у участника флаг стоит, но компания не продаёт."""
    company = Company.objects.create(name="Client co", inn="3001000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="member@caps.test", username="member@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,  # дефолт модели — именно он и вводил интерфейс в заблуждение
        can_buy=True,
    )

    data = MeSerializer(user).data
    assert data["can_sell"] is True, "плоское поле остаётся флагом участника"
    assert data["capabilities"]["can_sell"] is False, "capabilities знает тип компании"


def test_capability_can_sell_is_true_for_seller_company_member(lookups):
    user, _ = _seller_user("seller@caps.test", with_subscription=False)
    assert MeSerializer(user).data["capabilities"]["can_sell"] is True


def test_capability_can_sell_follows_revoked_member_flag(lookups):
    """Компания продаёт, но участнику продажи запрещены — стороной продавца он не считается."""
    company = Company.objects.create(name="Seller co", inn="3001000002")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="nosell@caps.test", username="nosell@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
        can_buy=True,
    )

    assert MeSerializer(user).data["capabilities"]["can_sell"] is False


def test_capability_can_sell_sees_secondary_seller_membership(lookups):
    """Основное членство в компании-покупателе не должно скрывать продавцовскую сторону."""
    buyer_company = Company.objects.create(name="Buyer primary", inn="3001000003")
    buyer_company.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_company = Company.objects.create(name="Seller secondary", inn="3001000004")
    seller_company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="dual@caps.test", username="dual@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=buyer_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
        can_buy=True,
    )
    CompanyMember.objects.create(
        user=user,
        company=seller_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=False,
        can_sell=True,
        can_buy=False,
    )

    assert MeSerializer(user).data["capabilities"]["can_sell"] is True
