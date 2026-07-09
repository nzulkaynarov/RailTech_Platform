"""Company Document Profile — tenant org-admin requisites for КП / contract documents.

Covers: the OWNER reads/updates THEIR OWN company's profile; another company's OWNER is
refused (403, never another tenant); a plain (non-OWNER) member is refused; the get-or-
create accessor and the service field whitelist.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyDocumentProfile, CompanyMember, CustomUser, WorkspaceRole
from accounts.services import update_document_profile


def _owner(company, email):
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_primary=True, is_active=True)
    return user


def _member(company, email, *, role_code="SALES_MANAGER"):
    ws = WorkspaceRole.objects.get_or_create(code=role_code, defaults={"name": role_code, "sort_order": 20})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_active=True)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def two_companies(db):
    seller_a = Company.objects.create(name="РемПуть")
    seller_b = Company.objects.create(name="Конкурент")
    owner_a = _owner(seller_a, "owner-a@a.test")
    owner_b = _owner(seller_b, "owner-b@b.test")
    return seller_a, owner_a, seller_b, owner_b


@pytest.mark.django_db
def test_get_creates_profile_for_owner(two_companies):
    seller_a, owner_a, _, _ = two_companies
    resp = _client(owner_a).get(f"/api/v1/accounts/companies/{seller_a.id}/document-profile/")
    assert resp.status_code == 200, resp.content
    assert resp.json()["company"] == seller_a.id
    assert CompanyDocumentProfile.objects.filter(company=seller_a).exists()


@pytest.mark.django_db
def test_owner_updates_own_profile(two_companies):
    seller_a, owner_a, _, _ = two_companies
    resp = _client(owner_a).patch(
        f"/api/v1/accounts/companies/{seller_a.id}/document-profile/",
        {"legal_name": "ООО «РемПуть»", "inn": "300123456", "footer_text": "С уважением, РемПуть."},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["legal_name"] == "ООО «РемПуть»"
    assert body["inn"] == "300123456"
    profile = CompanyDocumentProfile.objects.get(company=seller_a)
    assert profile.footer_text == "С уважением, РемПуть."


@pytest.mark.django_db
def test_other_owner_cannot_read_or_write(two_companies):
    seller_a, _, _, owner_b = two_companies
    # owner of B tries to touch A's profile → 403, never cross-tenant.
    read = _client(owner_b).get(f"/api/v1/accounts/companies/{seller_a.id}/document-profile/")
    assert read.status_code == 403
    write = _client(owner_b).patch(
        f"/api/v1/accounts/companies/{seller_a.id}/document-profile/",
        {"legal_name": "HACK"},
        format="json",
    )
    assert write.status_code == 403
    assert not CompanyDocumentProfile.objects.filter(company=seller_a, legal_name="HACK").exists()


@pytest.mark.django_db
def test_plain_member_cannot_edit(two_companies):
    seller_a, _, _, _ = two_companies
    sales = _member(seller_a, "sales@a.test")
    resp = _client(sales).patch(
        f"/api/v1/accounts/companies/{seller_a.id}/document-profile/",
        {"legal_name": "X"},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_service_rejects_non_owner_and_whitelists_fields(two_companies):
    seller_a, owner_a, _, owner_b = two_companies
    # non-owner → error, no profile mutated.
    _, error = update_document_profile(owner_b, seller_a, {"legal_name": "X"})
    assert error == "NOT_COMPANY_OWNER"
    # owner: only whitelisted textual fields are written; company/logo ignored.
    profile, error = update_document_profile(
        owner_a, seller_a, {"legal_name": "ООО А", "company": 999, "logo": "x", "bank_details": "р/с 123"}
    )
    assert error is None
    assert profile.company_id == seller_a.id
    assert profile.legal_name == "ООО А"
    assert profile.bank_details == "р/с 123"
    assert not profile.logo


@pytest.mark.django_db
def test_update_rejects_css_injection_accent_color(two_companies):
    """SEC audit #9: accent_color must be a #hex colour — a CSS-injection payload is refused
    (it would otherwise reach a <style> block in the PDF template → WeasyPrint SSRF)."""
    seller_a, owner_a, _, _ = two_companies
    profile, err = update_document_profile(owner_a, seller_a, {"accent_color": "red;background:url(http://10.0.0.2)"})
    assert profile is None
    assert err == "INVALID_ACCENT_COLOR"
    profile2, err2 = update_document_profile(owner_a, seller_a, {"accent_color": "#15294d"})
    assert err2 is None
    assert profile2.accent_color == "#15294d"
