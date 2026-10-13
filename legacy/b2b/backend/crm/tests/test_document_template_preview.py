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


def test_preview_returns_letterhead_brand(lookups):
    """T1-a: the preview carries the letterhead slice so the SPA renders the FULL branded document
    (header + body + footer), not the bare body — the seller's own name/ИНН print in the шапка."""
    company = _company("ООО Продавец-Бренд", "S9")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>{{deal.title}}</p>"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    brand = resp.json()["brand"]
    # The header prints the seller name + ИНН — proving the requisites already live in the letterhead.
    assert brand["seller_name"] == "ООО Продавец-Бренд"
    assert brand["inn"] == "S9"
    assert brand["accent"]
    assert brand["accent_contrast"]
    assert "footer_text" in brand


def test_preview_returns_full_document_html_from_real_template(lookups):
    """1:1 preview: the response carries document_html — the WHOLE branded document rendered by the
    REAL PDF template (crm/generated_document_pdf.html → _document_base.html), so the SPA iframe
    shows exactly what WeasyPrint prints instead of a hand-written React letterhead."""
    company = _company("ООО Полный-Документ", "S7")
    user = _member(company, "s@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/preview/",
        {"body_html": "<p>Тело {{deal.title}}</p>"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    document_html = resp.json()["document_html"]
    # Structural markers only the real base template emits (not the old React re-implementation):
    assert 'class="brandbar"' in document_html  # letterhead шапка table
    assert "--accent:" in document_html  # :root theme tokens
    assert "layout-" in document_html  # body layout-preset class
    assert 'class="doc-body"' in document_html  # generated_document_pdf.html body wrapper
    # …carrying the seller's own letterhead + the rendered body.
    assert "ООО Полный-Документ" in document_html
    assert "Демо-сделка" in document_html


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


def test_placeholder_catalog_returns_grouped_code_and_label(lookups):
    """T1-c: dynamic data vs company requisites already in the шапка; E1b добавил третью
    группу — структурные блоки юридических документов."""
    company = _company("Продавец", "S1")
    user = _member(company, "s@t.uz")
    resp = _api(user).get("/api/v1/crm/document-templates/placeholders/")
    assert resp.status_code == 200, resp.content
    groups = resp.json()["groups"]
    assert len(groups) == 3
    by_key = {group["key"]: group for group in groups}
    assert set(by_key) == {"dynamic", "company", "legal_blocks"}
    for group in groups:
        assert group["label"]
        assert group["items"]
        for entry in group["items"]:
            assert entry["code"]
            assert entry["label"]
    dynamic_codes = {entry["code"] for entry in by_key["dynamic"]["items"]}
    company_codes = {entry["code"] for entry in by_key["company"]["items"]}
    assert "deal.number" in dynamic_codes
    assert "counterparty.name" in dynamic_codes
    # The owner-company requisites live in the «уже в шапке» group, never in dynamic.
    assert "company.name" in company_codes
    assert "company.name" not in dynamic_codes


def test_placeholder_catalog_requires_auth(lookups):
    resp = APIClient().get("/api/v1/crm/document-templates/placeholders/")
    assert resp.status_code == 401
