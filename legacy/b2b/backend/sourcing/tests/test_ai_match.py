"""AI semantic match заявка→catalog (roadmap #1) — shortlist + Rule-1 validation + endpoint.

The Claude client is stubbed (no paid/nondeterministic calls); we assert the deterministic
contract: trigram shortlist, product_id must come from the DB shortlist, endpoint guards.
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import CompanyType, Company, CompanyMember, CustomUser, WorkspaceRole
from catalog.models import Product


def _stub_response(matches):
    text = __import__("json").dumps({"matches": matches})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.fixture
def products(db):
    p1 = Product.objects.create(name="Автосцепка СА-3", sku="RLM-004")
    p2 = Product.objects.create(name="Баббит Б-83", sku="MAT-001")
    return p1, p2


@pytest.mark.django_db
def test_shortlist_finds_by_trigram(products):
    from sourcing.services_ai import _shortlist_products

    found = _shortlist_products({"name": "Автосцепка", "mpn": "", "gost_drawing": ""}, None)
    assert any(p.name == "Автосцепка СА-3" for p in found)


@pytest.mark.django_db
def test_match_rejects_ids_outside_shortlist(products, settings, monkeypatch):
    """Rule 1: a product_id the model returns that is NOT in the DB shortlist is dropped."""
    settings.AI_IMPORT_ENABLED = True
    p1, _ = products
    # Model returns the real candidate AND a hallucinated id 99999 → only the real one survives.
    fake = _stub_response([{"line_index": 0, "candidates": [
        {"product_id": p1.id, "confidence": 0.9, "reason": "match"},
        {"product_id": 99999, "confidence": 0.99, "reason": "hallucinated"},
    ]}])
    monkeypatch.setattr(
        "sourcing.services_ai._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from sourcing.services_ai import match_lines_to_catalog

    res = match_lines_to_catalog([{"name": "Автосцепка", "mpn": "", "gost_drawing": ""}])
    ids = [c["product_id"] for m in res for c in m["candidates"]]
    assert p1.id in ids and 99999 not in ids


@pytest.mark.django_db
def test_match_disabled_returns_empty(products, settings):
    settings.AI_IMPORT_ENABLED = False
    from sourcing.services_ai import match_lines_to_catalog

    assert match_lines_to_catalog([{"name": "Автосцепка"}]) == []


@pytest.mark.django_db
def test_endpoint_guards(products, settings):
    settings.AI_IMPORT_ENABLED = True
    user = CustomUser.objects.create_user(email="m@x.test", username="m@x.test", password="pw", is_active=True)
    client = APIClient(); client.force_authenticate(user)
    # missing lines → 400
    assert client.post("/api/v1/sourcing/match-catalog/", {}, format="json").status_code == 400
    # disabled → 503
    settings.AI_IMPORT_ENABLED = False
    r = client.post("/api/v1/sourcing/match-catalog/", {"lines": [{"name": "x"}]}, format="json")
    assert r.status_code == 503
