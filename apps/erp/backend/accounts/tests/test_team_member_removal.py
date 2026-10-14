"""S3 (spec P2 + P8): company-team member removal / (de)activation API.

Thin company-team @action wrappers over the existing never-orphan services
(remove_company_member / toggle_user_active). Gated by the team.manage CompanyRole
permission — the OWNER holds it via the is_system «Администратор компании» role.
These endpoints are the company-plane self-service path (NOT the operator-plane
users.py toggle-active / remove-membership, which require users.manage).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole


def _owner_role():
    return WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]


def _member_role():
    return WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Sales Manager", "sort_order": 20}
    )[0]


def _admin_member(company, email):
    """A company admin holding team.manage via the is_system CompanyRole."""
    admin_role, _ = CompanyRole.objects.get_or_create(
        company=company, is_system=True, defaults={"name": "Админ", "permissions": ["team.manage"]}
    )
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    membership = CompanyMember.objects.create(
        user=user, company=company, role=_owner_role(), company_roles=[admin_role], is_active=True
    )
    return user, membership


def _plain_member(company, email):
    """A member WITHOUT team.manage."""
    role = CompanyRole.objects.create(company=company, name="Продажи", permissions=["quote.send"])
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    membership = CompanyMember.objects.create(
        user=user, company=company, role=_member_role(), company_roles=[role], is_active=True
    )
    return user, membership


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme LLC", inn="9911223344")


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# ─── remove-member ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_removes_member(company):
    admin_user, _admin = _admin_member(company, "admin@acme.test")
    _plain_user, plain = _plain_member(company, "sales@acme.test")

    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/remove-member/",
        {"member_id": plain.id},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["removed"] is True
    assert not CompanyMember.objects.filter(pk=plain.id).exists()


@pytest.mark.django_db
def test_remove_last_admin_blocked(company):
    admin_user, admin = _admin_member(company, "admin@acme.test")

    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/remove-member/",
        {"member_id": admin.id},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "CANNOT_REMOVE_LAST_COMPANY_ADMIN"
    assert CompanyMember.objects.filter(pk=admin.id).exists()  # still there


@pytest.mark.django_db
def test_remove_member_requires_team_manage(company):
    _admin_user, _admin = _admin_member(company, "admin@acme.test")
    plain_user, plain = _plain_member(company, "sales@acme.test")

    resp = _client(plain_user).post(
        f"/api/v1/accounts/companies/{company.id}/remove-member/",
        {"member_id": plain.id},
        format="json",
    )
    assert resp.status_code == 403
    assert CompanyMember.objects.filter(pk=plain.id).exists()


@pytest.mark.django_db
def test_remove_member_unknown_id(company):
    admin_user, _admin = _admin_member(company, "admin@acme.test")
    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/remove-member/",
        {"member_id": 999999},
        format="json",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "MEMBER_NOT_FOUND"


# ─── toggle-member-active ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_deactivates_and_reactivates_member(company):
    admin_user, _admin = _admin_member(company, "admin@acme.test")
    plain_user, plain = _plain_member(company, "sales@acme.test")

    # Deactivate
    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/toggle-member-active/",
        {"member_id": plain.id},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["is_active"] is False
    plain_user.refresh_from_db()
    assert plain_user.is_active is False

    # Reactivate
    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/toggle-member-active/",
        {"member_id": plain.id},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    plain_user.refresh_from_db()
    assert plain_user.is_active is True


@pytest.mark.django_db
def test_deactivate_sole_admin_blocked(company):
    admin_user, admin = _admin_member(company, "admin@acme.test")
    # A second admin to satisfy the actor-is-not-target path, but the TARGET is the sole
    # admin only if we deactivate the last one. Here admin is the sole admin → blocked.
    resp = _client(admin_user).post(
        f"/api/v1/accounts/companies/{company.id}/toggle-member-active/",
        {"member_id": admin.id},
        format="json",
    )
    # Self-deactivation guard fires first (actor == target) → CANNOT_DEACTIVATE_SELF (400).
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CANNOT_DEACTIVATE_SELF"
    admin_user.refresh_from_db()
    assert admin_user.is_active is True


@pytest.mark.django_db
def test_deactivate_sole_admin_by_delegate_blocked(company):
    """A delegate holding team.manage (custom role, NOT the admin floor) cannot deactivate
    the company's sole admin — never-orphan → 409 CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN.

    Using a non-admin delegate as the actor avoids the self-deactivation guard firing first.
    """
    admin_user, admin = _admin_member(company, "admin@acme.test")
    # Delegate: team.manage via a NON-system CompanyRole → not part of the admin floor.
    delegate_role = CompanyRole.objects.create(company=company, name="HR", permissions=["team.manage"])
    delegate_user = CustomUser.objects.create_user(
        email="hr@acme.test", username="hr@acme.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=delegate_user, company=company, role=_member_role(), company_roles=[delegate_role], is_active=True
    )

    resp = _client(delegate_user).post(
        f"/api/v1/accounts/companies/{company.id}/toggle-member-active/",
        {"member_id": admin.id},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN"
    admin_user.refresh_from_db()
    assert admin_user.is_active is True


@pytest.mark.django_db
def test_toggle_requires_team_manage(company):
    _admin_user, _admin = _admin_member(company, "admin@acme.test")
    plain_user, plain = _plain_member(company, "sales@acme.test")
    resp = _client(plain_user).post(
        f"/api/v1/accounts/companies/{company.id}/toggle-member-active/",
        {"member_id": plain.id},
        format="json",
    )
    assert resp.status_code == 403


# ─── real status in the team payload (P8) ───────────────────────────────────


@pytest.mark.django_db
def test_team_payload_exposes_is_active(company):
    admin_user, _admin = _admin_member(company, "admin@acme.test")
    plain_user, _plain = _plain_member(company, "sales@acme.test")
    plain_user.is_active = False
    plain_user.save(update_fields=["is_active"])

    resp = _client(admin_user).get(f"/api/v1/accounts/companies/{company.id}/team/")
    assert resp.status_code == 200
    by_email = {row["email"]: row for row in resp.json()}
    assert by_email["admin@acme.test"]["is_active"] is True
    assert by_email["sales@acme.test"]["is_active"] is False
