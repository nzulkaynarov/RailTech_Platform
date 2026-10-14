"""«Документы 2.0» — template library service + API (company-scope, IDOR, samples).

Self-contained lookup seeding (CI runs --nomigrations, so the 0068 data migration
that seeds DocumentTemplateKind / samples does not run here).
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm import services as crm_services
from crm.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocumentStatus


@pytest.fixture
def lookups(db):
    for code, name in (("LETTER", "Письмо"), ("REPORT", "Рапорт"), ("CUSTOM", "Произвольный")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "CANCELLED"):
        GeneratedDocumentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="LOGIST", defaults={"name": "Logist", "sort_order": 20})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
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
    if role_code == "OWNER":
        _grant_head(user, company)
    return user


def _grant_head(user, company):
    """M1-ERP-05: права сотрудника — только из ролей; прежний OWNER = роль «Руководитель»."""
    from accounts.services.roles import ensure_default_company_roles

    CompanyMember.objects.get(user=user, company=company).company_roles.add(
        ensure_default_company_roles(company)["HEAD"]
    )


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── Service layer ────────────────────────────────────────────────────────────


def test_create_template_sanitises_and_extracts(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "s@t.uz")
    template = crm_services.create_template(
        company,
        user,
        name="Гарантийное письмо",
        kind_code="LETTER",
        body_html="<p>Компания {{company.name}}</p><script>evil()</script>",
    )
    assert "<script>" not in template.body_html
    assert "evil" not in template.body_html
    assert "company.name" in template.placeholders_used


def test_update_template_reextracts_placeholders(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "s@t.uz")
    template = crm_services.create_template(company, user, name="X", kind_code="CUSTOM", body_html="{{deal.number}}")
    assert template.placeholders_used == ["deal.number"]
    crm_services.update_template(template, body_html="{{company.inn}} {{today}}")
    template.refresh_from_db()
    assert set(template.placeholders_used) == {"company.inn", "today"}


# ── API: scope / IDOR / samples ──────────────────────────────────────────────


def test_owner_can_create_via_api(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "owner@t.uz")
    resp = _api(user).post(
        "/api/v1/crm/document-templates/",
        {"name": "Рапорт", "kind": "REPORT", "body_html": "<p>{{today}}</p>"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert DocumentTemplate.objects.filter(company=company, name="Рапорт").exists()


def test_non_privileged_member_cannot_create(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "logist@t.uz", role_code="LOGIST")  # no OWNER, no caps → no settings.edit
    resp = _api(user).post(
        "/api/v1/crm/document-templates/",
        {"name": "X", "kind": "CUSTOM", "body_html": "<p>hi</p>"},
        format="json",
    )
    assert resp.status_code == 403


def test_queryset_scoped_to_own_plus_samples(lookups):
    company_a = _company("A", "A1")
    user_a = _member(company_a, "a@t.uz")
    own = crm_services.create_template(company_a, user_a, name="Own", kind_code="CUSTOM", body_html="x")
    company_b = _company("B", "B1")
    user_b = _member(company_b, "b@t.uz")
    foreign = crm_services.create_template(company_b, user_b, name="Foreign", kind_code="CUSTOM", body_html="y")
    sample = DocumentTemplate.objects.create(
        company=None,
        name="Образец",
        kind=DocumentTemplateKind.objects.get(code="LETTER"),
        is_sample=True,
        body_html="s",
    )

    ids = {row["id"] for row in _api(user_a).get("/api/v1/crm/document-templates/").json()}
    assert own.id in ids
    assert sample.id in ids
    assert foreign.id not in ids


def test_idor_foreign_template_not_retrievable(lookups):
    company_a = _company("A", "A1")
    user_a = _member(company_a, "a@t.uz")
    company_b = _company("B", "B1")
    user_b = _member(company_b, "b@t.uz")
    foreign = crm_services.create_template(company_b, user_b, name="Foreign", kind_code="CUSTOM", body_html="y")

    resp = _api(user_a).get(f"/api/v1/crm/document-templates/{foreign.id}/")
    assert resp.status_code == 404


def test_sample_can_be_copied_into_own_company(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "s@t.uz")
    sample = DocumentTemplate.objects.create(
        company=None,
        name="Доверенность",
        kind=DocumentTemplateKind.objects.get(code="LETTER"),
        is_sample=True,
        body_html="<p>{{company.name}}</p>",
    )
    resp = _api(user).post(f"/api/v1/crm/document-templates/{sample.id}/copy/")
    assert resp.status_code == 201, resp.content
    copy = DocumentTemplate.objects.get(company=company, name="Доверенность")
    assert copy.is_sample is False
    assert copy.company_id == company.id
