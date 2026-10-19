"""Catalog AI tools (PIM enrich) are gated by the catalog.manage ROLE permission.

M1-ERP-02 wave 2 removed the paid ai.enrich entitlement (subscription / per-company grant): the
enrich endpoint is now open to whoever runs the catalog — a staff member holding catalog.manage
(M1-ERP-05: only from roles, no OWNER fallback) — and refused with ROLE_NOT_PERMITTED otherwise,
with nothing enqueued. extract is gated by the КП/contract roles, not the catalog role.

The Celery publish is stubbed; these assert the synchronous gate only.
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole


@pytest.fixture
def stub_apply_async(monkeypatch):
    """Record run_ai_job.apply_async calls so we can assert a job was / was not enqueued."""
    calls = []
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: calls.append((args, task_id)) or SimpleNamespace(id=task_id),
    )
    return calls


def _seller_company(inn, *, type_code="SUPPLIER"):
    company_type = CompanyType.objects.get_or_create(code=type_code, defaults={"name": type_code, "sort_order": 10})[0]
    company = Company.objects.create(name=f"Company {inn}", inn=inn)
    company.types.add(company_type)
    return company


def _seller_user(email, company, *, permissions=None):
    """OWNER member with can_sell; with `permissions` — bound to a CompanyRole carrying exactly them."""
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    company_role = None
    if permissions is not None:
        company_role = CompanyRole.objects.create(company=company, name=f"Роль {email}", permissions=permissions)
    CompanyMember.objects.create(
        user=user, company=company, role=owner_role, is_active=True, can_sell=True, company_roles=[company_role]
    )
    return user


def _enrich(client):
    return client.post("/api/v1/catalog/product-enrich/", {"name": "Тормозная колодка"}, format="json")


# ── enrich: gated on the catalog.manage role permission ──────────────────────


@pytest.mark.django_db
def test_enrich_for_catalog_manager_passes_without_any_plan(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000001")
    user = _seller_user("manager@x.test", company, permissions=["catalog.manage"])
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 202
    assert len(stub_apply_async) == 1


@pytest.mark.django_db
def test_enrich_for_owner_without_role_is_forbidden(settings, stub_apply_async):
    """M1-ERP-05: должность OWNER без роли прав не даёт."""
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000002")
    user = _seller_user("owner@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "ROLE_NOT_PERMITTED"}
    assert stub_apply_async == []


@pytest.mark.django_db
def test_enrich_without_catalog_manage_is_forbidden(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000003")
    user = _seller_user("viewer@x.test", company, permissions=["quote.build"])
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "ROLE_NOT_PERMITTED"}
    assert stub_apply_async == []  # nothing queued, no paid LLM call


@pytest.mark.django_db
def test_enrich_for_buyer_side_member_is_forbidden(settings, stub_apply_async):
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000004", type_code="CLIENT")
    user = _seller_user("buyer@x.test", company)
    client = APIClient()
    client.force_authenticate(user)

    response = _enrich(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "ROLE_NOT_PERMITTED"}
    assert stub_apply_async == []


# ── extract: not gated by the catalog role ────────────────────────────


@pytest.mark.django_db
def test_extract_is_not_catalog_gated(settings, stub_apply_async):
    """extract has no catalog gate: a staff member with quote.build (или contract.manage) passes the
    gate and only trips the reference-resolution guard (404 REFERENCE_NOT_FOUND) — NEVER a 403 wall."""
    settings.AI_IMPORT_ENABLED = True
    company = _seller_company("7200000006")
    user = _seller_user("extract@x.test", company, permissions=["quote.build"])
    client = APIClient()
    client.force_authenticate(user)

    from django.core.files.uploadedfile import SimpleUploadedFile

    # A .txt upload has no magic-byte signature → passes the content check; a bogus quote_id
    # then fails visibility resolution with 404 (proving no 403 gate ran first).
    upload = SimpleUploadedFile("doc.txt", b"total 100 UZS", content_type="text/plain")
    response = client.post(
        "/api/v1/sourcing/extract-document/",
        {"file": upload, "quote_id": 999999},
        format="multipart",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "REFERENCE_NOT_FOUND"}
    assert stub_apply_async == []  # never reached enqueue, but crucially not a 403 either
