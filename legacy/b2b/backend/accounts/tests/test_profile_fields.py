"""Regression tests for the profile-field audit (user + company).

Covers the gaps the audit surfaced:
  * /me/ now returns `position` (was collected at registration, then dropped);
  * self-update writes name/phone/position but NEVER email/username/is_active;
  * the client company serializer no longer leaks internal `kyc_notes`;
  * a company OWNER may edit their own company, a plain member may not, and
    KYC trust verdicts (is_verified / trust_score) stay read-only for everyone
    but the platform.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/accounts/users/me/"
UPDATE_ME_URL = "/api/v1/accounts/users/update-me/"


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _make_member(user, company, workspace_role_factory, *, role_code, role_name):
    role = workspace_role_factory(code=role_code, name=role_name)
    return CompanyMember.objects.create(
        user=user, company=company, role=role, is_primary=True, is_active=True
    )


def test_me_returns_position(user_factory):
    user = user_factory(email="pos@example.com", username="pos")
    user.position = "Директор по закупкам"
    user.save(update_fields=["position"])

    resp = _client_for(user).get(ME_URL)

    assert resp.status_code == 200
    assert resp.data["position"] == "Директор по закупкам"


def test_update_me_writes_profile_but_not_identity(user_factory):
    user = user_factory(email="self@example.com", username="self")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {
            "position": "Логист",
            "phone": "+998901112233",
            # The following must be ignored — they are not self-editable.
            "email": "hacker@evil.com",
            "username": "hacker",
            "is_active": False,
        },
        format="json",
    )

    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.position == "Логист"
    assert user.phone == "+998901112233"
    assert user.email == "self@example.com"
    assert user.username == "self"
    assert user.is_active is True


def test_company_detail_hides_kyc_notes(user_factory, company_factory, workspace_role_factory):
    company = company_factory(kyc_notes="internal manager note — do not show")
    user = user_factory(email="owner@example.com", username="owner")
    _make_member(user, company, workspace_role_factory, role_code="OWNER", role_name="Owner")

    resp = _client_for(user).get(f"/api/v1/accounts/companies/{company.id}/")

    assert resp.status_code == 200
    assert "kyc_notes" not in resp.data


def test_owner_can_edit_company_but_not_trust_signals(user_factory, company_factory, workspace_role_factory):
    company = company_factory()
    user = user_factory(email="owner2@example.com", username="owner2")
    _make_member(user, company, workspace_role_factory, role_code="OWNER", role_name="Owner")

    resp = _client_for(user).patch(
        f"/api/v1/accounts/companies/{company.id}/",
        {"phone": "+998900000000", "is_verified": True, "trust_score": 99},
        format="json",
    )

    assert resp.status_code == 200
    company.refresh_from_db()
    assert company.phone == "+998900000000"
    # Trust verdicts are platform-controlled — a company must not self-set them.
    assert company.is_verified is False
    assert company.trust_score == 0


def test_non_owner_member_cannot_edit_company(user_factory, company_factory, workspace_role_factory):
    company = company_factory()
    user = user_factory(email="member@example.com", username="member")
    _make_member(user, company, workspace_role_factory, role_code="SALES_MANAGER", role_name="Sales Manager")

    resp = _client_for(user).patch(
        f"/api/v1/accounts/companies/{company.id}/",
        {"phone": "+998900000000"},
        format="json",
    )

    assert resp.status_code == 403
