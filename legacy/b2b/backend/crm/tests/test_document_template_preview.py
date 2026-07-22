"""«Документы 2.0» — template editor live-preview + placeholder catalogue endpoints.

Own test file (append-conflict trap). Self-contained lookup seeding (CI runs
--nomigrations, so the data migration that seeds DocumentTemplateKind does not run).
Covers: sanitisation on preview, placeholder resolution on demo data, unknown-code
warnings, real company.* data, oversize-body guard, catalogue shape, auth gate.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.services.generated_documents import MAX_TEMPLATE_BODY_CHARS


@pytest.fixture
def lookups(db):
    for code, name in (("LETTER", "Письмо"), ("REPORT", "Рапорт"), ("CUSTOM", "Произвольный")):
        from crm.models import DocumentTemplateKind

        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})


def _company(name, inn):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return company


def _member(company, email, *, role_code="OWNER"):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code=role_code), is_active=True, is_primary=True
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── preview ───────────────────────────────────────────────────────────────────


def test_preview_sanitises_script(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>Привет</p><script>evil()</script>"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    html = resp.json()["rendered_html"]
    assert "<script>" not in html
    assert "evil" not in html
    assert "Привет" in html


def test_preview_resolves_known_placeholders_on_demo_data(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>{{deal.title}} — {{quote.number}} — {{contract.number}}</p>"},
        format="json",
    )
    body = resp.json()
    assert resp.status_code == 200, resp.content
    assert "Демо-сделка" in body["rendered_html"]
    assert "КП-2026-00042" in body["rendered_html"]
    assert "ДГ-2026-00007" in body["rendered_html"]
    assert set(body["placeholders_used"]) == {"deal.title", "quote.number", "contract.number"}
    assert body["warnings"] == []


def test_preview_uses_real_company_name(lookups):
    company = _company("ООО Реальная Компания", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>{{company.name}} / {{company.inn}}</p>"},
        format="json",
    )
    html = resp.json()["rendered_html"]
    assert "ООО Реальная Компания" in html
    assert "S1" in html


def test_preview_warns_on_unknown_placeholder(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>{{settings.SECRET_KEY}}</p>"},
        format="json",
    )
    body = resp.json()
    assert resp.status_code == 200
    assert "settings.SECRET_KEY" in body["warnings"]
    assert "settings.SECRET_KEY" not in body["placeholders_used"]
    # Unknown token is left verbatim (never evaluated — no SSTI).
    assert "{{settings.SECRET_KEY}}" in body["rendered_html"]


def test_preview_empty_body_ok(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post("/api/v1/crm/document-templates/preview/", {}, format="json")
    assert resp.status_code == 200
    assert resp.json()["rendered_html"] == ""


def test_preview_oversize_body_rejected(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "a" * (MAX_TEMPLATE_BODY_CHARS + 1)},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "TEMPLATE_BODY_TOO_LARGE"


def test_preview_requires_auth(lookups):
    resp = APIClient().post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>x</p>"},
        format="json",
    )
    assert resp.status_code == 401


# ── placeholder catalogue ─────────────────────────────────────────────────────


def test_placeholder_catalog_returns_code_and_label(lookups):
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).get("/api/v1/crm/document-templates/placeholders/")
    assert resp.status_code == 200, resp.content
    placeholders = resp.json()["placeholders"]
    assert len(placeholders) > 0
    for entry in placeholders:
        assert entry["code"]
        assert entry["label"]
    codes = {entry["code"] for entry in placeholders}
    assert "deal.number" in codes
    assert "company.name" in codes


def test_placeholder_catalog_requires_auth(lookups):
    resp = APIClient().get("/api/v1/crm/document-templates/placeholders/")
    assert resp.status_code == 401
