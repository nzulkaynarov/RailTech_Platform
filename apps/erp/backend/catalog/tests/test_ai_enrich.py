"""AI #2 PIM product enrichment — disabled→{}, spec normalisation, category-hint-only.

The LiteLLM gateway is faked (ai.testing.FakeGateway) (no paid/nondeterministic calls); we assert the deterministic
contract: gated on AI_IMPORT_ENABLED, specs cleaned/dropped, category returned as a HINT
string (never an id — Rule 1), and the endpoint guards (400 missing name, 503 disabled).
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole


def _seller_user(email):
    """Сотрудник своей компании с ролью, дающей `catalog.manage` (M1-ERP-05) — проходит гейт,
    и обогащение доходит до постановки в очередь."""
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})[
        0
    ]
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    company = Company.objects.create(name="Enrich Seller", inn="7100000001")
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    role = CompanyRole.objects.create(company=company, name="Каталог", permissions=["catalog.manage"])
    CompanyMember.objects.create(
        user=user, company=company, role=owner_role, is_active=True, can_sell=True, company_roles=[role]
    )
    return user


@pytest.mark.django_db
def test_enrich_disabled_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = False
    from catalog.ai_enrich import enrich_product

    assert enrich_product("Тормозная колодка") == {}


@pytest.mark.django_db
def test_enrich_empty_name_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = True
    from catalog.ai_enrich import enrich_product

    # No name → neutral {} without any model call (so a stub-less env is fine).
    assert enrich_product("   ") == {}


@pytest.mark.django_db
def test_enrich_normalises_and_keeps_category_as_hint(fake_gateway):
    """Rule 1: category is a HINT string only; spec rows without a key are dropped."""
    fake_gateway.reply_json(
        {
            "description": "Композитная тормозная колодка для грузовых вагонов.",
            "specifications": [
                {"key": "Материал", "value": "Композит"},
                {"key": "", "value": "сирота"},  # no key → dropped
            ],
            "suggested_category_hint": "Тормозное оборудование",
        }
    )
    from catalog.ai_enrich import enrich_product

    result = enrich_product("Тормозная колодка композитная", domain_code="GENERAL_GOODS")
    assert result["description"].startswith("Композитная")
    assert result["specifications"] == [{"key": "Материал", "value": "Композит"}]
    # HINT only — a plain string, never a resolved Category id.
    assert result["suggested_category_hint"] == "Тормозное оборудование"
    assert isinstance(result["suggested_category_hint"], str)
    body = fake_gateway.last_body
    assert body["model"] == "enrich-model"
    assert body["metadata"]["tags"] == ["system=erp", "feature=enrich", "model=enrich-model"]


@pytest.mark.django_db
def test_enrich_refusal_returns_empty(fake_gateway):
    fake_gateway.reply_refusal()
    from catalog.ai_enrich import enrich_product

    assert enrich_product("Болт М12") == {}


@pytest.mark.django_db
def test_enrich_gateway_error_is_a_logged_noop(fake_gateway):
    fake_gateway.reply_http_error(503)
    from catalog.ai_enrich import enrich_product

    assert enrich_product("Болт М12") == {}


@pytest.mark.django_db
def test_enrich_endpoint_guards(settings, monkeypatch):
    # The URL route + throttle scope are wired by the orchestrator in core/urls.py +
    # core/settings.py (this bucket must not touch those shared files). Skip the HTTP
    # contract assertions until the route exists so the unit tests above still run.
    from django.urls import NoReverseMatch, reverse

    try:
        url = reverse("product-enrich")
    except NoReverseMatch:
        pytest.skip("product-enrich route not wired yet (orchestrator registers it in core/urls.py)")

    settings.AI_IMPORT_ENABLED = True
    user = _seller_user("en@x.test")
    client = APIClient()
    client.force_authenticate(user)
    # missing name → 400
    assert client.post(url, {}, format="json").status_code == 400
    # ARCH-01: valid input → the LLM call is queued on Celery — 202 {task_id} + an owned AIJob row.
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: SimpleNamespace(id=task_id),
    )
    ok = client.post(url, {"name": "Тормозная колодка"}, format="json")
    assert ok.status_code == 202
    task_id = ok.json()["task_id"]
    from sourcing.models import AIJob

    assert AIJob.objects.filter(celery_task_id=task_id, owner=user, feature="enrich").exists()
    # disabled → 503
    settings.AI_IMPORT_ENABLED = False
    response = client.post(url, {"name": "x"}, format="json")
    assert response.status_code == 503
