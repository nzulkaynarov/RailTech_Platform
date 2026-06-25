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


def _stub_extract_response(items):
    text = __import__("json").dumps({"items": items})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.mark.django_db
def test_shortlist_finds_by_trigram(products):
    from sourcing.services_ai import _shortlist_products

    found = _shortlist_products({"name": "Автосцепка", "mpn": "", "gost_drawing": ""}, None)
    assert any(p.name == "Автосцепка СА-3" for p in found)


@pytest.mark.django_db
def test_shortlist_uses_name_canonical_for_latin_query(products):
    """Bilingual win: a Latin raw name trigram-misses the Cyrillic catalog, but the
    canonical Russian `name_canonical` preselects the right row (Greatest similarity)."""
    from sourcing.services_ai import _shortlist_products

    line = {"name": "Avtoscepka SA-3", "name_canonical": "Автосцепка СА-3", "mpn": "", "gost_drawing": ""}
    found = _shortlist_products(line, None)
    assert any(p.name == "Автосцепка СА-3" for p in found)

    # Without the canonical form the Latin query alone preselects nothing useful —
    # proves the canonical name is what carries the match.
    latin_only = {"name": "Avtoscepka SA-3", "name_canonical": "", "mpn": "", "gost_drawing": ""}
    assert not any(p.name == "Автосцепка СА-3" for p in _shortlist_products(latin_only, None))


@pytest.mark.django_db
def test_extract_returns_canonical_russian_name(settings, monkeypatch):
    """A Latin input line is normalised to a canonical Russian `name_canonical`,
    while the original `name` is preserved verbatim."""
    settings.AI_IMPORT_ENABLED = True
    settings.AI_IMPORT_MODEL = "stub-model"
    settings.AI_IMPORT_CHUNK_ROWS = 100
    fake = _stub_extract_response([
        {
            "name": "Tormoznaya koloda",
            "name_canonical": "Тормозная колодка",
            "quantity": 2,
            "unit": "шт.",
            "unit_code": "",
            "mpn": "",
            "gost_drawing": "",
            "note": "",
        }
    ])
    monkeypatch.setattr(
        "sourcing.services_ai._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    # Avoid DB hit for the unit-code справочник; the model returned ''.
    monkeypatch.setattr("sourcing.services_ai._unit_code_reference", lambda: (set(), ""))
    from sourcing.services_ai import extract_request_items

    items = extract_request_items(b"Tormoznaya koloda,2,sht\n", "request.csv")
    assert len(items) == 1
    assert items[0]["name"] == "Tormoznaya koloda"  # original untouched
    assert items[0]["name_canonical"] == "Тормозная колодка"  # canonical Russian captured


@pytest.mark.django_db
def test_normalize_falls_back_to_name_when_canonical_missing():
    """Old/empty model output without name_canonical falls back to the raw name."""
    from sourcing.services_ai import _normalize_items

    cleaned = _normalize_items(
        [{"name": "Баббит Б-83", "quantity": 1, "unit": "", "unit_code": "", "mpn": "", "gost_drawing": "", "note": ""}],
        valid_codes=set(),
    )
    assert cleaned[0]["name_canonical"] == "Баббит Б-83"


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

    res = match_lines_to_catalog(
        [{"name": "Avtoscepka", "name_canonical": "Автосцепка", "mpn": "", "gost_drawing": ""}]
    )
    ids = [c["product_id"] for m in res for c in m["candidates"]]
    assert p1.id in ids and 99999 not in ids
    # Canonical Russian name is echoed back so the caller can persist it on QuoteItem.
    assert res[0]["name_canonical"] == "Автосцепка"


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
