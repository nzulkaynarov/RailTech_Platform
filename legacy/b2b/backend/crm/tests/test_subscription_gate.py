"""F0.2 — subscription gate on paid seller writes.

A SELLER team without an operational SupplierSubscription must be blocked from
the monetised seller actions (send КП, generate/sign contract, issue invoice/act)
with the stable `SUBSCRIPTION_REQUIRED` code. Superuser bypasses (DBA). The gate
fires *before* the target row is loaded, so these tests stay fixture-light.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    WorkspaceRole,
)
from accounts.services import assert_seller_can_operate
from crm import services as crm_services
from crm.models import Quote


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})


def _seller_user(email="seller@gate.test", *, with_subscription, operational=True):
    """A SUPPLIER-company OWNER with can_sell, optionally with a subscription."""
    company = Company.objects.create(name=f"Seller {email}", inn=email)
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


# ── unit: assert_seller_can_operate ──────────────────────────────────────────


def test_seller_without_subscription_is_blocked(lookups):
    user, _ = _seller_user(with_subscription=False)
    assert assert_seller_can_operate(user) == "SUBSCRIPTION_REQUIRED"


def test_seller_with_operational_subscription_passes(lookups):
    user, _ = _seller_user(email="ok@gate.test", with_subscription=True, operational=True)
    assert assert_seller_can_operate(user) is None


def test_seller_with_past_due_subscription_is_blocked(lookups):
    user, _ = _seller_user(email="pastdue@gate.test", with_subscription=True, operational=False)
    assert assert_seller_can_operate(user) == "SUBSCRIPTION_REQUIRED"


def test_superuser_bypasses_subscription_gate(db):
    admin = CustomUser.objects.create_superuser(email="su@gate.test", username="su@gate.test", password="x")
    assert assert_seller_can_operate(admin) is None


# ── integration: the gate fires inside the seller-write services ─────────────


def test_generate_contract_blocked_without_subscription(lookups):
    """Gate runs before the Quote is loaded → SUBSCRIPTION_REQUIRED with a bogus id."""
    user, _ = _seller_user(email="gc-block@gate.test", with_subscription=False)
    contract, err = crm_services.generate_contract_from_quote(999999, actor=user)
    assert contract is None
    assert err == "SUBSCRIPTION_REQUIRED"


def test_generate_contract_passes_gate_with_subscription(lookups):
    """With an operational subscription the gate is cleared, so execution reaches
    the (missing) quote lookup and raises — i.e. it is NOT SUBSCRIPTION_REQUIRED."""
    user, _ = _seller_user(email="gc-ok@gate.test", with_subscription=True, operational=True)
    with pytest.raises(Quote.DoesNotExist):
        crm_services.generate_contract_from_quote(999999, actor=user)
