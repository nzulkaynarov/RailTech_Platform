"""Tests for the entitlement layer (ADR-0006 §3 monetization) — has_entitlement / credits / grant."""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.constants import FeatureKey
from accounts.models import Company, CompanyEntitlement, SupplierSubscription
from accounts.services.entitlements import (
    can_send_kp,
    consume_credit,
    grant_entitlement,
    has_entitlement,
    is_demo,
)


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme", inn="1234500001")


def _operational_sub(company):
    return SupplierSubscription.objects.create(
        company=company, plan="BASIC", status="ACTIVE",
        valid_from=timezone.now().date(), valid_until=(timezone.now() + timedelta(days=365)).date(),
    )


def test_free_floor_always_granted_without_a_row(company):
    assert has_entitlement(company.id, FeatureKey.AI_MATCH) is True
    assert has_entitlement(company.id, FeatureKey.AI_PREFLIGHT) is True


def test_non_floor_feature_locked_without_a_row(company):
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is False


# ─── monetization gate: subscription baseline + can_send_kp ──────────────────


def test_operational_subscription_grants_send_baseline(company):
    _operational_sub(company)
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is True
    assert can_send_kp(company.id) is True


def test_no_subscription_no_send(company):
    assert can_send_kp(company.id) is False  # build is free; send is not


def test_explicit_disable_overrides_subscription(company):
    _operational_sub(company)
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="DISABLED")  # admin revoke wins
    assert can_send_kp(company.id) is False


def test_demo_blocks_send_even_with_subscription(company):
    _operational_sub(company)
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="DEMO")
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is True  # usable (build)...
    assert can_send_kp(company.id) is False  # ...but demo can't actually send


def test_promo_grant_allows_send_without_subscription(company):
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="ENABLED")  # promo, no subscription
    assert can_send_kp(company.id) is True


def test_enabled_row_grants_disabled_revokes(company):
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="ENABLED")
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is True
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="DISABLED")
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is False


def test_expired_entitlement_not_granted(company):
    grant_entitlement(
        company.id, FeatureKey.KP_EXPORT, access="ENABLED", expires_at=timezone.now() - timedelta(days=1)
    )
    assert has_entitlement(company.id, FeatureKey.KP_EXPORT) is False


def test_demo_access_is_granted_and_flagged(company):
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="DEMO")
    assert has_entitlement(company.id, FeatureKey.KP_SEND) is True  # usable...
    assert is_demo(company.id, FeatureKey.KP_SEND) is True  # ...but the caller knows to watermark/gate


def test_credit_metering_consumes_and_blocks_when_exhausted(company):
    grant_entitlement(company.id, FeatureKey.AI_DRAFT, access="ENABLED", credits=2)
    assert has_entitlement(company.id, FeatureKey.AI_DRAFT) is True
    assert consume_credit(company.id, FeatureKey.AI_DRAFT) is True   # 2 → 1
    assert consume_credit(company.id, FeatureKey.AI_DRAFT) is True   # 1 → 0
    assert consume_credit(company.id, FeatureKey.AI_DRAFT) is False  # exhausted
    assert has_entitlement(company.id, FeatureKey.AI_DRAFT) is False  # 0 credits ⇒ not granted
    assert CompanyEntitlement.objects.get(company=company, feature_key="ai.draft").credits == 0


def test_unmetered_grant_never_decrements(company):
    grant_entitlement(company.id, FeatureKey.AI_DRAFT, access="ENABLED", credits=None)
    assert consume_credit(company.id, FeatureKey.AI_DRAFT, amount=99) is True
    assert has_entitlement(company.id, FeatureKey.AI_DRAFT) is True


def test_free_floor_consume_is_noop_true(company):
    assert consume_credit(company.id, FeatureKey.AI_MATCH, amount=5) is True


def test_grant_is_upsert_one_row_per_feature(company):
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="ENABLED")
    grant_entitlement(company.id, FeatureKey.KP_SEND, access="DEMO", note="downgraded")
    rows = CompanyEntitlement.objects.filter(company=company, feature_key="kp.send")
    assert rows.count() == 1 and rows.first().access == "DEMO"
