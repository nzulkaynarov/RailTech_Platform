"""Tier-aware daily AI cap + per-company operator override (owner decision 2026-07-28).

Each subscription plan maps to a daily AI allowance (Старт=BASIC / Про=STANDARD / Безлимит=
PREMIUM=unlimited); a free company falls back to AI_DAILY_JOB_CAP_FREE. An operator can override
ONE company's ceiling via a CompanyEntitlement(ai.daily_cap).limit row — it wins over the plan.

Celery publish is stubbed (as in test_ai_spend_cap.py).
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from accounts.constants import FeatureKey
from accounts.models import Company, CompanyEntitlement, CompanyMember, CustomUser, SupplierSubscription, WorkspaceRole
from sourcing.ai_jobs import enqueue_ai_job
from sourcing.models import AIJob


@pytest.fixture
def stub_apply_async(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: calls.append((args, task_id)) or SimpleNamespace(id=task_id),
    )
    return calls


def _owner_role():
    return WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]


def _member(email, company):
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=_owner_role(), is_active=True)
    return user


def _seed_jobs(owner, count):
    for index in range(count):
        AIJob.objects.create(celery_task_id=f"seed-{owner.id}-{index}", owner=owner, feature="match")


def _subscribe(company, plan):
    return SupplierSubscription.objects.create(company=company, plan=plan)  # TRIAL + no expiry → operational


# ── plan tiers map to distinct ceilings ───────────────────────────────────────


@pytest.mark.django_db
def test_standard_plan_uses_standard_cap(settings, stub_apply_async):
    settings.AI_DAILY_CAP_BASIC = 5
    settings.AI_DAILY_CAP_STANDARD = 20
    company = Company.objects.create(name="Pro Co", inn="820000001")
    _subscribe(company, "STANDARD")  # Про
    user = _member("pro@x.test", company)
    _seed_jobs(user, 10)  # over BASIC(5), under STANDARD(20)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 202


@pytest.mark.django_db
def test_premium_plan_is_unlimited(settings, stub_apply_async):
    settings.AI_DAILY_CAP_PREMIUM = 0  # Безлимит
    company = Company.objects.create(name="Unlimited Co", inn="820000002")
    _subscribe(company, "PREMIUM")
    user = _member("premium@x.test", company)
    _seed_jobs(user, 500)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 202


@pytest.mark.django_db
def test_basic_plan_blocks_at_basic_cap(settings, stub_apply_async):
    settings.AI_DAILY_CAP_BASIC = 3
    company = Company.objects.create(name="Start Co", inn="820000003")
    _subscribe(company, "BASIC")  # Старт
    user = _member("start@x.test", company)
    _seed_jobs(user, 3)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 429


# ── per-company operator override wins over the plan tier ──────────────────────


@pytest.mark.django_db
def test_override_lifts_the_cap(settings, stub_apply_async):
    """Promo/VIP: operator grants a company a higher daily ceiling than its plan."""
    settings.AI_DAILY_CAP_BASIC = 3
    company = Company.objects.create(name="VIP Co", inn="820000004")
    _subscribe(company, "BASIC")
    CompanyEntitlement.objects.create(company=company, feature_key=FeatureKey.AI_DAILY_CAP.value, limit=50)
    user = _member("vip@x.test", company)
    _seed_jobs(user, 10)  # over BASIC(3) but under the override(50)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 202


@pytest.mark.django_db
def test_override_throttles_below_plan(settings, stub_apply_async):
    """Abuse throttle: operator caps a company BELOW its plan allowance."""
    settings.AI_DAILY_CAP_STANDARD = 300
    company = Company.objects.create(name="Throttled Co", inn="820000005")
    _subscribe(company, "STANDARD")
    CompanyEntitlement.objects.create(company=company, feature_key=FeatureKey.AI_DAILY_CAP.value, limit=5)
    user = _member("throttled@x.test", company)
    _seed_jobs(user, 5)  # at the override ceiling, far under the plan

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 429


@pytest.mark.django_db
def test_expired_override_falls_back_to_plan(settings, stub_apply_async):
    settings.AI_DAILY_CAP_STANDARD = 20
    company = Company.objects.create(name="Expired Override Co", inn="820000006")
    _subscribe(company, "STANDARD")
    CompanyEntitlement.objects.create(
        company=company,
        feature_key=FeatureKey.AI_DAILY_CAP.value,
        limit=5,
        expires_at=timezone.now() - timedelta(days=1),  # expired → ignored
    )
    user = _member("expired@x.test", company)
    _seed_jobs(user, 10)  # over the expired override(5), under the plan(20)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 202


@pytest.mark.django_db
def test_override_limit_zero_is_ignored(settings, stub_apply_async):
    """limit=0 is NOT "unlimited" — it means unset; fall through to the plan tier."""
    settings.AI_DAILY_CAP_BASIC = 3
    company = Company.objects.create(name="Zero Override Co", inn="820000007")
    _subscribe(company, "BASIC")
    CompanyEntitlement.objects.create(company=company, feature_key=FeatureKey.AI_DAILY_CAP.value, limit=0)
    user = _member("zero@x.test", company)
    _seed_jobs(user, 3)  # at the plan ceiling (override ignored)

    assert enqueue_ai_job("match", {"lines": []}, user).status_code == 429
