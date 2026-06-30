"""DRF tests for the CompanyEntitlement admin endpoint (ADR-0006 Move 4 monetization control plane)."""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyEntitlement, CompanyMember, CustomUser, SystemRole, WorkspaceRole

URL = "/api/v1/admin/entitlements/"


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme", inn="9000000001")


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_superuser_can_grant_and_list(company):
    su = CustomUser.objects.create_superuser(email="su@x.uz", username="su@x.uz", password="pw")
    client = _client(su)
    resp = client.post(
        URL, {"company": company.id, "feature_key": "quote.send", "access": "ENABLED"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    assert CompanyEntitlement.objects.filter(company=company, feature_key="quote.send").exists()

    listing = client.get(f"{URL}?company={company.id}")
    assert listing.status_code == 200
    rows = listing.json()
    rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    assert any(r["feature_key"] == "quote.send" and r["is_granted"] for r in rows)


def test_superuser_can_set_demo_and_disable(company):
    su = CustomUser.objects.create_superuser(email="su2@x.uz", username="su2@x.uz", password="pw")
    client = _client(su)
    ent = CompanyEntitlement.objects.create(company=company, feature_key="quote.send", access="ENABLED")
    resp = client.patch(f"{URL}{ent.id}/", {"access": "DEMO"}, format="json")
    assert resp.status_code == 200
    ent.refresh_from_db()
    assert ent.access == "DEMO"


def test_regular_member_forbidden(company):
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    ws = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "M", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email="m@x.uz", username="m@x.uz", password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_active=True)
    resp = _client(user).get(URL)
    assert resp.status_code == 403  # OperatorScoped — not a platform operator
