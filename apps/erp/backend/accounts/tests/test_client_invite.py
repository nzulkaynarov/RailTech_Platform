"""Tests for CB-invite — registering an offline counterparty (CRM Phase D).

A seller invites an offline client's contact to register and CLAIM the existing offline Company
(flip is_registered=True) instead of creating a duplicate. Token is one-time, expiring, scoped.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    ClientInvite,
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from accounts.services.clients import _hash_invite_token, accept_client_invite, send_client_invite
from accounts.services.profile import submit_company_profile


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="PROFILE_SUBMITTED", defaults={"name": "Submitted", "sort_order": 10})


def _seller(lookups):
    company = Company.objects.create(name="Seller Co", inn="DS100")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(
        email="d-seller@t.test", username="d-seller@t.test", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _offline_client_with_contact(seller_user, email="client@offline.test"):
    from accounts.services.clients import create_offline_client

    result, err = create_offline_client(
        seller=seller_user,
        company_name="Оффлайн Клиент",
        contact_name="Азиз",
        email=email,
    )
    assert err is None
    return result["company"], result["contact"]


# ── send_client_invite ──────────────────────────────────────────────────────


def test_send_invite_creates_row_and_link(lookups, settings):
    seller_user, _ = _seller(lookups)
    company, contact = _offline_client_with_contact(seller_user)
    invite, err = send_client_invite(seller=seller_user, contact_id=contact.id)
    assert err is None
    assert invite.company_id == company.id and invite.email == "client@offline.test"
    assert invite.accepted_at is None and invite.expires_at > timezone.now()


def test_send_invite_rejects_foreign_contact(lookups):
    seller_user, _ = _seller(lookups)
    other_user = CustomUser.objects.create_user(email="d-other@t.test", username="d-other@t.test", password="x")
    other_co = Company.objects.create(name="Other Seller", inn="DS200")
    other_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    CompanyMember.objects.create(
        user=other_user,
        company=other_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    _company, contact = _offline_client_with_contact(seller_user)
    invite, err = send_client_invite(seller=other_user, contact_id=contact.id)
    assert invite is None and err == "CONTACT_NOT_IN_YOUR_BOOK"


def test_send_invite_rejects_registered_company(lookups):
    seller_user, _ = _seller(lookups)
    _company, contact = _offline_client_with_contact(seller_user)
    contact.company.is_registered = True
    contact.company.save(update_fields=["is_registered"])
    invite, err = send_client_invite(seller=seller_user, contact_id=contact.id)
    assert invite is None and err == "COMPANY_ALREADY_REGISTERED"


def test_send_invite_rejects_existing_user_email(lookups):
    seller_user, _ = _seller(lookups)
    _company, contact = _offline_client_with_contact(seller_user, email="taken@offline.test")
    CustomUser.objects.create_user(email="taken@offline.test", username="taken@offline.test", password="x")
    invite, err = send_client_invite(seller=seller_user, contact_id=contact.id)
    assert invite is None and err == "USER_EMAIL_ALREADY_EXISTS"


# ── accept via submit_company_profile ───────────────────────────────────────


def _raw_token_for(invite):
    """Reconstruct isn't possible (hash-only) — re-issue a known token by overwriting the hash."""
    token = "known-raw-token-xyz"
    invite.token_hash = _hash_invite_token(token)
    invite.save(update_fields=["token_hash"])
    return token


def test_accept_claims_existing_company_no_duplicate(lookups):
    seller_user, _ = _seller(lookups)
    company, contact = _offline_client_with_contact(seller_user)
    invite, _ = send_client_invite(seller=seller_user, contact_id=contact.id)
    token = _raw_token_for(invite)

    invitee = CustomUser.objects.create_user(
        email="client@offline.test", username="client@offline.test", password="x", is_active=True
    )
    before_count = Company.objects.count()
    user, err = submit_company_profile(invitee, company_name="ignored", position="Директор", invite_token=token)
    assert err is None
    assert Company.objects.count() == before_count  # NO new company — claimed the existing one
    company.refresh_from_db()
    assert company.is_registered is True
    assert invitee.memberships.filter(company=company, is_primary=True).exists()
    invite.refresh_from_db()
    assert invite.accepted_at is not None


def test_accept_is_one_time(lookups):
    seller_user, _ = _seller(lookups)
    _company, contact = _offline_client_with_contact(seller_user)
    invite, _ = send_client_invite(seller=seller_user, contact_id=contact.id)
    token = _raw_token_for(invite)
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_at"])
    result, err = accept_client_invite(CustomUser(), token)
    assert result is None and err == "CLIENT_INVITE_INVALID"


def test_accept_rejects_expired(lookups):
    seller_user, _ = _seller(lookups)
    _company, contact = _offline_client_with_contact(seller_user)
    invite, _ = send_client_invite(seller=seller_user, contact_id=contact.id)
    token = _raw_token_for(invite)
    invite.expires_at = timezone.now() - timedelta(minutes=1)
    invite.save(update_fields=["expires_at"])
    result, err = accept_client_invite(CustomUser(), token)
    assert result is None and err == "CLIENT_INVITE_INVALID"


def test_accept_rejects_garbage_token(lookups):
    result, err = accept_client_invite(CustomUser(), "not-a-real-token")
    assert result is None and err == "CLIENT_INVITE_INVALID"


def test_submit_without_invite_still_creates_new_company(lookups):
    user = CustomUser.objects.create_user(email="fresh@t.test", username="fresh@t.test", password="x", is_active=True)
    before = Company.objects.count()
    _user, err = submit_company_profile(user, company_name="Brand New LLC", position="CEO")
    assert err is None and Company.objects.count() == before + 1


# ── endpoint ────────────────────────────────────────────────────────────────


def test_invite_endpoint(lookups):
    seller_user, _ = _seller(lookups)
    _company, contact = _offline_client_with_contact(seller_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(seller_user).access_token}")
    resp = client.post(f"/api/v1/accounts/contacts/{contact.id}/invite/")
    assert resp.status_code == 200 and resp.json()["invited"] is True
    assert ClientInvite.objects.filter(company=contact.company).exists()
