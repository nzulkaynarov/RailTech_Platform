"""Regression tests for the profile-field audit (user + company).

Covers the gaps the audit surfaced:
  * /me/ now returns `position`;
  * self-update writes name/phone/position but NEVER email/username/is_active;
  * a company OWNER may edit their own company, a plain member may not, and
    the trust verdict (trust_score) stays read-only for everyone but the platform.
    (KYC — kyc_notes / is_verified — was removed in M1-ERP-02 wave 1c.)
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember
from accounts.testing import grant_head, make_own_company

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
    return CompanyMember.objects.create(user=user, company=company, role=role, is_primary=True, is_active=True)


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


def test_update_me_accepts_valid_preferences(user_factory):
    user = user_factory(email="prefs-ok@example.com", username="prefs-ok")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": {"language": "en", "theme": "dark"}},
        format="json",
    )

    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.preferences == {"language": "en", "theme": "dark"}


def test_update_me_rejects_unknown_preference_key(user_factory):
    user = user_factory(email="prefs-key@example.com", username="prefs-key")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": {"language": "en", "is_admin": True}},
        format="json",
    )

    assert resp.status_code == 400
    assert "PREFERENCES_UNKNOWN_KEY" in str(resp.data["preferences"])
    user.refresh_from_db()
    assert user.preferences == {}


def test_update_me_rejects_invalid_preference_value(user_factory):
    user = user_factory(email="prefs-val@example.com", username="prefs-val")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": {"language": "fr"}},
        format="json",
    )

    assert resp.status_code == 400
    assert "PREFERENCES_INVALID_LANGUAGE" in str(resp.data["preferences"])


def test_update_me_rejects_invalid_theme(user_factory):
    user = user_factory(email="prefs-theme@example.com", username="prefs-theme")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": {"theme": "neon"}},
        format="json",
    )

    assert resp.status_code == 400
    assert "PREFERENCES_INVALID_THEME" in str(resp.data["preferences"])


def test_update_me_rejects_oversized_preferences(user_factory):
    user = user_factory(email="prefs-big@example.com", username="prefs-big")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": {"timezone": "A" * 5000}},
        format="json",
    )

    assert resp.status_code == 400
    # Size cap trips before the per-key length check.
    assert "PREFERENCES_TOO_LARGE" in str(resp.data["preferences"])
    user.refresh_from_db()
    assert user.preferences == {}


def test_update_me_rejects_non_object_preferences(user_factory):
    user = user_factory(email="prefs-list@example.com", username="prefs-list")

    resp = _client_for(user).patch(
        UPDATE_ME_URL,
        {"preferences": ["language", "en"]},
        format="json",
    )

    assert resp.status_code == 400
    assert "PREFERENCES_INVALID" in str(resp.data["preferences"])


def test_owner_can_edit_company_but_not_trust_signals(user_factory, company_factory, workspace_role_factory):
    company = make_own_company(company_factory())
    user = user_factory(email="owner2@example.com", username="owner2")
    _make_member(user, company, workspace_role_factory, role_code="OWNER", role_name="Owner")
    grant_head(user, company)

    resp = _client_for(user).patch(
        f"/api/v1/accounts/companies/{company.id}/",
        {"phone": "+998900000000", "trust_score": 99},
        format="json",
    )

    assert resp.status_code == 200
    company.refresh_from_db()
    assert company.phone == "+998900000000"
    # Trust verdicts are platform-controlled — a company must not self-set them.
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
