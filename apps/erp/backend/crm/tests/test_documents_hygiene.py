"""«Документы 2.0» — F3 «Гигиена» fixes.

III-1: DELETE of a template that already produced documents → 400 TEMPLATE_IN_USE (not a 500
       from the on_delete=PROTECT ProtectedError); an unused template still hard-deletes (204).
III-5: the live-preview action carries a dedicated throttle class.
III-6: generation/issue/send is gated on the quote.build CompanyRole permission — a buy-only
       member cannot produce branded company documents; the OWNER keeps the ability.

Self-contained lookup seeding (CI runs --nomigrations).
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm import services as crm_services
from crm.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from crm.views.documents import DocumentPreviewThrottle, DocumentTemplateViewSet


@pytest.fixture
def lookups(db):
    for code, name in (("LETTER", "Письмо"), ("CUSTOM", "Произвольный")):
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


def _member(company, email, *, role_code="OWNER", can_sell=True):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=role_code),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
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


def _template(company, user, body="<p>{{today}}</p>"):
    return crm_services.create_template(company, user, name="Письмо", kind_code="LETTER", body_html=body)


@pytest.fixture
def world(lookups):
    company = _company("Seller", "S1")
    owner = _member(company, "owner@t.uz")
    return company, owner


# ── III-1: PROTECT on template delete → 400, not 500 ─────────────────────────


def test_delete_template_in_use_returns_400_not_500(world):
    company, owner = world
    template = _template(company, owner)
    # A rendered document pins the template (GeneratedDocument.template = on_delete=PROTECT).
    GeneratedDocument.objects.create(
        company=company,
        template=template,
        number="DOC-2026-00001",
        status=GeneratedDocumentStatus.objects.get(code="DRAFT"),
        title="Письмо",
        created_by=owner,
    )
    resp = _api(owner).delete(f"/api/v1/crm/document-templates/{template.id}/")
    assert resp.status_code == 400, resp.content
    assert resp.json()["detail"] == "TEMPLATE_IN_USE"
    assert DocumentTemplate.objects.filter(pk=template.id).exists()  # not deleted


def test_delete_unused_template_succeeds(world):
    company, owner = world
    template = _template(company, owner)
    resp = _api(owner).delete(f"/api/v1/crm/document-templates/{template.id}/")
    assert resp.status_code == 204, resp.content
    assert not DocumentTemplate.objects.filter(pk=template.id).exists()


# ── III-5: preview action carries a dedicated throttle ───────────────────────


def test_preview_action_has_dedicated_throttle():
    action = DocumentTemplateViewSet.preview
    throttles = getattr(action, "kwargs", {}).get("throttle_classes", [])
    assert DocumentPreviewThrottle in throttles
    assert DocumentPreviewThrottle.scope == "document_preview"


# ── III-6: quote.build gate on generation / issue ────────────────────────────


def test_buy_only_member_cannot_generate(world):
    company, _owner = world
    junior = _member(company, "junior@t.uz", role_code="LOGIST", can_sell=False)
    document, err = crm_services.generate_document(company, junior, template=_template(company, junior))
    assert document is None
    assert err == "ROLE_NOT_PERMITTED"


def test_buy_only_member_cannot_issue(world):
    company, owner = world
    document, err = crm_services.generate_document(company, owner, template=_template(company, owner))
    assert err is None
    junior = _member(company, "junior@t.uz", role_code="LOGIST", can_sell=False)
    _, issue_err = crm_services.issue_document(document, junior)
    assert issue_err == "ROLE_NOT_PERMITTED"


def test_owner_can_generate_and_issue(world):
    company, owner = world
    document, err = crm_services.generate_document(company, owner, template=_template(company, owner))
    assert err is None
    assert document.status_code == "DRAFT"
    issued, issue_err = crm_services.issue_document(document, owner)
    assert issue_err is None
    assert issued.status_code == "ISSUED"
