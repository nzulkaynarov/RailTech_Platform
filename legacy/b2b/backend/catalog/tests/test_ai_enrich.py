"""AI #2 PIM product enrichment — disabled→{}, spec normalisation, category-hint-only.

The Claude client is stubbed (no paid/nondeterministic calls); we assert the deterministic
contract: gated on AI_IMPORT_ENABLED, specs cleaned/dropped, category returned as a HINT
string (never an id — Rule 1), and the endpoint guards (400 missing name, 503 disabled).
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser


def _stub_response(payload):
    text = __import__("json").dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


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
def test_enrich_normalises_and_keeps_category_as_hint(settings, monkeypatch):
    """Rule 1: category is a HINT string only; spec rows without a key are dropped."""
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        {
            "description": "Композитная тормозная колодка для грузовых вагонов.",
            "specifications": [
                {"key": "Материал", "value": "Композит"},
                {"key": "", "value": "сирота"},  # no key → dropped
            ],
            "suggested_category_hint": "Тормозное оборудование",
        }
    )
    monkeypatch.setattr(
        "catalog.ai_enrich._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from catalog.ai_enrich import enrich_product

    result = enrich_product("Тормозная колодка композитная", domain_code="RAILWAY_MACHINERY")
    assert result["description"].startswith("Композитная")
    assert result["specifications"] == [{"key": "Материал", "value": "Композит"}]
    # HINT only — a plain string, never a resolved Category id.
    assert result["suggested_category_hint"] == "Тормозное оборудование"
    assert isinstance(result["suggested_category_hint"], str)


@pytest.mark.django_db
def test_enrich_refusal_returns_empty(settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    fake = SimpleNamespace(
        content=[],
        stop_reason="refusal",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0),
    )
    monkeypatch.setattr(
        "catalog.ai_enrich._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
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
    user = CustomUser.objects.create_user(email="en@x.test", username="en@x.test", password="pw", is_active=True)
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
