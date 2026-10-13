"""P1 (audit #13) — AI monetization gating for the enrich / extract / compose endpoints.

Policy (owner-approved matrix):
  * enrich  → SELLER PREMIUM: gated on the ai.enrich entitlement (operational subscription
    grants it by baseline; an explicit CompanyEntitlement row overrides). No entitlement → 403
    AI_FEATURE_NOT_ENTITLED and NOTHING is enqueued.
  * extract / compose → DELIBERATELY UNGATED (buyer-acquisition wedge funnel) — a subscription-less
    company still reaches them (no 403 entitlement wall).

The Celery publish is stubbed; these assert the synchronous policy gate only.
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.constants import FeatureKey
from accounts.models import (
    Company,
    CompanyEntitlement,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    WorkspaceRole,
)


@pytest.fixture
def stub_apply_async(monkeypatch):
    """Record run_ai_job.apply_async calls so we can assert a job was / was not enqueued."""
    calls = []
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: calls.append((args, task_id)) or SimpleNamespace(id=task_id),
    )
    return calls


def _seller_company(inn, *, subscribed):
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})[
        0
    ]
    company = Company.objects.create(name=f"Seller {inn}", inn=inn)
    company.types.add(supplier_type)
    if subscribed:
        SupplierSubscription.objects.create(company=company)  # TRIAL + no expiry → operational
    return company


def _seller_user(email, company):
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=owner_role, is_active=True, can_sell=True)
    return user


def _enrich(client):
    return client.post("/api/v1/catalog/product-enrich/", {"name": "Тормозная колодка"}, format="json")


# ── enrich: gated on the ai.enrich entitlement ────────────────────────────────


@pytest.mark.django_db
def test_enrich_without_subscription_is_forbidden(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000001", subscribed=False)
    user = _seller_user("nosub@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "AI_FEATURE_NOT_ENTITLED"}
    assert stub_apply_async == []  # nothing queued, no paid call / credit


@pytest.mark.django_db
def test_enrich_with_operational_subscription_passes(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000002", subscribed=True)
    user = _seller_user("sub@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


@pytest.mark.django_db
def test_enrich_with_explicit_entitlement_passes_without_subscription(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000003", subscribed=False)
    CompanyEntitlement.objects.create(company=company, feature_key=FeatureKey.AI_ENRICH.value, access="ENABLED")
    user = _seller_user("promo@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


@pytest.mark.django_db
def test_enrich_explicit_disabled_override_beats_subscription(settings, stub_apply_async):
    """An explicit non-granted CompanyEntitlement (DEMO downgrade / DISABLED) overrides the
    subscription baseline → 403, even for a paying tenant."""
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000004", subscribed=True)
    CompanyEntitlement.objects.create(company=company, feature_key=FeatureKey.AI_ENRICH.value, access="DISABLED")
    user = _seller_user("downgraded@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "AI_FEATURE_NOT_ENTITLED"}
    assert stub_apply_async == []


# ── extract / compose: NOT entitlement-gated (wedge funnel) ────────────────────


@pytest.mark.django_db
def test_compose_without_subscription_is_not_gated(settings, stub_apply_async):
    """compose reaches the enqueue for a subscription-less company — no 403 entitlement wall."""
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000005", subscribed=False)
    user = _seller_user("compose@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = client.post("/api/v1/sourcing/compose-request/", {"text": "нужны тормозные колодки"}, format="json")

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


@pytest.mark.django_db
def test_extract_without_subscription_is_not_gated(settings, stub_apply_async):
    """extract is not entitlement-gated: a subscription-less user passes the gate stage and only
    trips the reference-resolution guard (404 REFERENCE_NOT_FOUND) — NEVER a 403 entitlement wall."""
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000006", subscribed=False)
    user = _seller_user("extract@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    from django.core.files.uploadedfile import SimpleUploadedFile

    # A .txt upload has no magic-byte signature → passes the content check; a bogus quote_id
    # then fails visibility resolution with 404 (proving no entitlement gate ran first).
    upload = SimpleUploadedFile("doc.txt", b"total 100 UZS", content_type="text/plain")
    response = client.post(
        "/api/v1/sourcing/extract-document/",
        {"file": upload, "quote_id": 999999},
        format="multipart",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "REFERENCE_NOT_FOUND"}
    assert stub_apply_async == []  # never reached enqueue, but crucially not a 403 either
