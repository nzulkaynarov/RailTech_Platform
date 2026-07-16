"""P1 — two-tier daily AI-job spend cap.

A company WITHOUT an operational subscription gets the tighter ``AI_DAILY_JOB_CAP_FREE``;
a subscribed (ACTIVE/TRIAL) company gets the generous ``AI_DAILY_JOB_CAP_PER_COMPANY``.
The tier is decided by the subscription alone. Each tier can be disabled independently (<= 0).
The cap applies to EVERY interactive AI feature (free-floor match and the ungated wedge
features included) since they all funnel through the one enqueue choke-point.

Celery publish is stubbed (as in test_ai_spend_cap.py).
"""

from types import SimpleNamespace

import pytest

from accounts.models import Company, CompanyMember, CustomUser, SupplierSubscription, WorkspaceRole
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


# ── free tier: unsubscribed company hits the tighter free ceiling ─────────────


@pytest.mark.django_db
def test_free_company_uses_free_cap(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_FREE = 2
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 300
    company = Company.objects.create(name="Free Co", inn="810000001")  # no subscription
    user = _member("free@x.test", company)
    _seed_jobs(user, 2)  # free ceiling reached

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 429
    assert response.data == {"detail": "AI_DAILY_CAP_REACHED"}
    assert stub_apply_async == []


@pytest.mark.django_db
def test_free_company_below_free_cap_enqueues(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_FREE = 2
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 300
    company = Company.objects.create(name="Free Under Co", inn="810000002")
    user = _member("free-under@x.test", company)
    _seed_jobs(user, 1)  # 1 of 2

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


# ── paid tier: subscribed company gets the generous ceiling ───────────────────


@pytest.mark.django_db
def test_subscribed_company_uses_higher_cap(settings, stub_apply_async):
    """At the free ceiling but subscribed → still allowed (the paid ceiling applies)."""
    settings.AI_DAILY_JOB_CAP_FREE = 2
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 5
    company = Company.objects.create(name="Paid Co", inn="810000003")
    SupplierSubscription.objects.create(company=company)  # TRIAL + no expiry → operational
    user = _member("paid@x.test", company)
    _seed_jobs(user, 2)  # would block a free company, but this one is subscribed

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


@pytest.mark.django_db
def test_subscribed_company_blocked_at_paid_cap(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_FREE = 2
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 5
    company = Company.objects.create(name="Paid Full Co", inn="810000004")
    SupplierSubscription.objects.create(company=company)
    user = _member("paid-full@x.test", company)
    _seed_jobs(user, 5)  # paid ceiling reached

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 429
    assert stub_apply_async == []


# ── the two-tier cap applies to the ungated wedge features too ────────────────


@pytest.mark.django_db
def test_free_cap_also_covers_wedge_features(settings, stub_apply_async):
    """extract / compose are entitlement-free but still share the daily fuse."""
    settings.AI_DAILY_JOB_CAP_FREE = 2
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 300
    company = Company.objects.create(name="Wedge Cap Co", inn="810000005")
    user = _member("wedge@x.test", company)
    _seed_jobs(user, 2)

    assert enqueue_ai_job("compose", {"text": "x"}, user).status_code == 429
    assert enqueue_ai_job("extract", {"file_key": "k"}, user).status_code == 429
    assert stub_apply_async == []


# ── free tier disabled (0): unsubscribed company is uncapped ───────────────────


@pytest.mark.django_db
def test_free_cap_zero_disables_free_tier(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_FREE = 0
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 5
    company = Company.objects.create(name="Uncapped Free Co", inn="810000006")
    user = _member("uncapped-free@x.test", company)
    _seed_jobs(user, 50)  # far past the paid ceiling, but the free tier is disabled

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1
