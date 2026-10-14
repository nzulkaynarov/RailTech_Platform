"""Security audit #13 — per-company daily AI-job spend cap.

The cap is enforced at the single enqueue choke-point (``enqueue_ai_job``): under
the ceiling a job queues normally (202 + AIJob row + published task); at the ceiling
the request is refused with 429 ``AI_DAILY_CAP_REACHED`` — no row written, no task
published. Coverage: below cap passes, at cap blocks, cap=0 disables,
yesterday's jobs don't count toward today, and different companies have independent buckets.

Celery is never touched — ``run_ai_job.apply_async`` is stubbed (as in test_ai_jobs.py).
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from sourcing.ai_jobs import enqueue_ai_job
from sourcing.models import AIJob


@pytest.fixture
def stub_apply_async(monkeypatch):
    """Stub run_ai_job.apply_async; record (args, task_id) so we can assert it did / didn't run."""
    calls = []

    def _apply_async(args=None, task_id=None, **kwargs):
        calls.append((args, task_id))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("sourcing.tasks_ai.run_ai_job.apply_async", _apply_async)
    return calls


def _owner_role():
    return WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(email, company):
    user = _user(email)
    CompanyMember.objects.create(user=user, company=company, role=_owner_role(), is_active=True)
    return user


def _seed_jobs(owner, count, *, days_ago=0):
    """Create ``count`` AIJob rows for ``owner``; created_at is auto_now_add so backdate via update."""
    for index in range(count):
        job = AIJob.objects.create(celery_task_id=f"seed-{owner.id}-{days_ago}-{index}", owner=owner, feature="match")
        if days_ago:
            AIJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=days_ago))


# ── below the cap: enqueue proceeds normally ──────────────────────────────────


@pytest.mark.django_db
def test_below_cap_enqueues(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    company = Company.objects.create(name="Under Cap Co", inn="111000111")
    user = _member("under-cap@x.test", company)
    _seed_jobs(user, 2)  # N-1 of 3 already used today

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    task_id = response.data["task_id"]
    assert stub_apply_async == [(["match", {"lines": []}], task_id)]
    assert AIJob.objects.filter(owner=user).count() == 3  # the 2 seeded + the new one


# ── at the cap: refuse with 429, nothing queued or spent ──────────────────────


@pytest.mark.django_db
def test_at_cap_returns_429_and_does_not_enqueue(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    company = Company.objects.create(name="At Cap Co", inn="222000222")
    user = _member("at-cap@x.test", company)
    _seed_jobs(user, 3)  # cap reached

    response = enqueue_ai_job("draft_quote", {"deal_id": 1}, user)

    assert response.status_code == 429
    assert response.data == {"detail": "AI_DAILY_CAP_REACHED"}
    assert stub_apply_async == []  # no paid task published
    assert AIJob.objects.filter(owner=user).count() == 3  # no new ownership row


# ── the cap counts the WHOLE team, not just the caller ────────────────────────


@pytest.mark.django_db
def test_cap_is_shared_across_company_members(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    company = Company.objects.create(name="Team Cap Co", inn="333000333")
    colleague = _member("teammate@x.test", company)
    user = _member("late-caller@x.test", company)
    _seed_jobs(colleague, 3)  # a teammate already exhausted the shared bucket

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 429
    assert stub_apply_async == []


# ── cap disabled (<= 0): unlimited ────────────────────────────────────────────


@pytest.mark.django_db
def test_cap_zero_disables_limit(settings, stub_apply_async):
    # Both tiers disabled → unlimited for any company (opt-out).
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 0
    company = Company.objects.create(name="No Cap Co", inn="444000444")
    user = _member("no-cap@x.test", company)
    _seed_jobs(user, 50)  # far past any generous ceiling

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


# ── yesterday's jobs don't count toward today's bucket ────────────────────────


@pytest.mark.django_db
def test_yesterday_jobs_do_not_count_today(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    company = Company.objects.create(name="Rollover Co", inn="555000555")
    user = _member("rollover@x.test", company)
    _seed_jobs(user, 5, days_ago=1)  # yesterday — outside today's calendar day

    response = enqueue_ai_job("match", {"lines": []}, user)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


# ── different companies have independent buckets ──────────────────────────────


@pytest.mark.django_db
def test_companies_are_independent(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    capped = Company.objects.create(name="Capped Co", inn="666000666")
    fresh = Company.objects.create(name="Fresh Co", inn="777000777")
    capped_user = _member("capped-co@x.test", capped)
    fresh_user = _member("fresh-co@x.test", fresh)
    _seed_jobs(capped_user, 3)  # only the capped company is exhausted

    blocked = enqueue_ai_job("match", {"lines": []}, capped_user)
    allowed = enqueue_ai_job("match", {"lines": []}, fresh_user)

    assert blocked.status_code == 429
    assert allowed.status_code == 202
    assert len(stub_apply_async) == 1  # only the fresh company's job was published


# ── exemptions: platform admin and users with no company ──────────────────────


@pytest.mark.django_db
def test_platform_admin_is_exempt(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    admin = _user("platform-admin@x.test")
    admin.is_superuser = True  # is_superuser → True (no memberships)
    admin.save(update_fields=["is_superuser"])
    _seed_jobs(admin, 10)

    response = enqueue_ai_job("match", {"lines": []}, admin)

    assert response.status_code == 202


@pytest.mark.django_db
def test_user_without_company_is_exempt(settings, stub_apply_async):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 3
    lone = _user("no-company@x.test")  # no CompanyMember rows
    _seed_jobs(lone, 10)

    response = enqueue_ai_job("match", {"lines": []}, lone)

    assert response.status_code == 202
