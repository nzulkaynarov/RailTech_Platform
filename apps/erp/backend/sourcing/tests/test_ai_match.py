"""AI semantic match заявка→catalog (roadmap #1) — shortlist + Rule-1 validation + endpoint.

The LiteLLM gateway is faked (ai.testing.FakeGateway) (no paid/nondeterministic calls); we assert the deterministic
contract: trigram shortlist, product_id must come from the DB shortlist, endpoint guards.
"""

from types import SimpleNamespace

import pytest
from ai.testing import install_fake_gateway
from rest_framework.test import APIClient

from accounts.models import CustomUser
from catalog.models import Product


def _stub_response(matches):
    return {"matches": matches}


@pytest.fixture
def products(db):
    from catalog.models import ProductStatus

    # PUBLISHED — the shortlist only surfaces published cards (review 2026-06-25 #3).
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 1})[0]
    p1 = Product.objects.create(name="Автосцепка СА-3", sku="RLM-004", status=pub)
    p2 = Product.objects.create(name="Баббит Б-83", sku="MAT-001", status=pub)
    return p1, p2


def _stub_extract_response(items):
    return {"items": items}


@pytest.mark.django_db
def test_shortlist_finds_by_trigram(products):
    from ai.services.matching import shortlist_products as _shortlist_products

    found = _shortlist_products({"name": "Автосцепка", "mpn": "", "gost_drawing": ""}, None)
    assert any(p.name == "Автосцепка СА-3" for p in found)


@pytest.mark.django_db
def test_shortlist_uses_name_canonical_for_latin_query(products):
    """Bilingual win: a Latin raw name trigram-misses the Cyrillic catalog, but the
    canonical Russian `name_canonical` preselects the right row (Greatest similarity)."""
    from ai.services.matching import shortlist_products as _shortlist_products

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
    settings.AI_IMPORT_CHUNK_ROWS = 100
    fake = _stub_extract_response(
        [
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
        ]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
    # Avoid DB hit for the unit-code справочник; the model returned ''.
    monkeypatch.setattr("ai.services.intake.unit_code_reference", lambda: (set(), ""))
    from sourcing.services_ai import extract_request_items

    items = extract_request_items(b"Tormoznaya koloda,2,sht\n", "request.csv")
    assert len(items) == 1
    assert items[0]["name"] == "Tormoznaya koloda"  # original untouched
    assert items[0]["name_canonical"] == "Тормозная колодка"  # canonical Russian captured


@pytest.mark.django_db
def test_normalize_falls_back_to_name_when_canonical_missing():
    """Old/empty model output without name_canonical falls back to the raw name."""
    from ai.services.intake import normalize_items as _normalize_items

    cleaned = _normalize_items(
        [
            {
                "name": "Баббит Б-83",
                "quantity": 1,
                "unit": "",
                "unit_code": "",
                "mpn": "",
                "gost_drawing": "",
                "note": "",
            }
        ],
        valid_codes=set(),
    )
    assert cleaned[0]["name_canonical"] == "Баббит Б-83"


@pytest.mark.django_db
def test_match_rejects_ids_outside_shortlist(products, settings, monkeypatch):
    """Rule 1: a product_id the model returns that is NOT in the DB shortlist is dropped."""
    settings.AI_IMPORT_ENABLED = True
    p1, _ = products
    # Model returns the real candidate AND a hallucinated id 99999 → only the real one survives.
    fake = _stub_response(
        [
            {
                "line_index": 0,
                "candidates": [
                    {"product_id": p1.id, "confidence": 0.9, "reason": "match"},
                    {"product_id": 99999, "confidence": 0.99, "reason": "hallucinated"},
                ],
            }
        ]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
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
def test_endpoint_guards(products, settings, monkeypatch, grant):
    settings.AI_IMPORT_ENABLED = True
    from accounts.models import Company, CompanyMember, CompanyType, WorkspaceRole

    user = CustomUser.objects.create_user(email="m@x.test", username="m@x.test", password="pw", is_active=True)
    own = Company.objects.create(name="Своя", inn="7702000001")
    own.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "S"})[0])
    CompanyMember.objects.create(user=user, company=own, role=WorkspaceRole.objects.get(code="MEMBER"), is_primary=True)
    grant(user, "quote.build")  # M1-ERP-05: подбор по каталогу — право роли расчёта
    client = APIClient()
    client.force_authenticate(user)
    # missing lines → 400
    assert client.post("/api/v1/sourcing/match-catalog/", {}, format="json").status_code == 400
    # ARCH-01: valid input → the LLM call is queued on Celery — 202 {task_id} + an owned AIJob row.
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: SimpleNamespace(id=task_id),
    )
    ok = client.post("/api/v1/sourcing/match-catalog/", {"lines": [{"name": "x"}]}, format="json")
    assert ok.status_code == 202
    task_id = ok.json()["task_id"]
    from sourcing.models import AIJob

    assert AIJob.objects.filter(celery_task_id=task_id, owner=user, feature="match").exists()
    # disabled → 503
    settings.AI_IMPORT_ENABLED = False
    r = client.post("/api/v1/sourcing/match-catalog/", {"lines": [{"name": "x"}]}, format="json")
    assert r.status_code == 503


@pytest.mark.django_db
def test_shortlist_excludes_unpublished_products(db):
    """Regression (review 2026-06-25 #3): the AI catalog shortlist must not surface DRAFT/
    ARCHIVED cards — only PUBLISHED ones, mirroring the catalog list endpoint."""
    from ai.services.matching import shortlist_products as _shortlist_products

    from catalog.models import Product, ProductStatus

    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "P", "sort_order": 1})[0]
    drf = ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 1})[0]
    Product.objects.create(name="SecretWidgetXYZ", status=drf)
    Product.objects.create(name="SecretWidgetXYZ", status=pub)
    names = [p.name for p in _shortlist_products({"name": "SecretWidgetXYZ"}, None)]
    statuses = {p.status.code for p in _shortlist_products({"name": "SecretWidgetXYZ"}, None)}
    assert names, "published match should be found"
    assert statuses == {"PUBLISHED"}, f"shortlist leaked non-published: {statuses}"
