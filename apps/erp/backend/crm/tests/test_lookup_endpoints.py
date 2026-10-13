"""Guards the lightweight {code,name} lookup feeds the frontend dropdowns consume.

Regression: QuoteStatusViewSet lost its custom list() (it has no serializer_class)
and 500'd. These tests hit the list endpoints so that can't recur silently.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser
from crm.models import ChargeType, QuoteStatus


@pytest.fixture
def auth_client(db):
    user = CustomUser.objects.create_user(
        email="lookup@example.com", username="lookup@example.com", password="pw", is_active=True
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_quote_statuses_list_returns_code_name(auth_client):
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    resp = auth_client.get("/api/v1/crm/quote-statuses/", SERVER_NAME="localhost")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["code"] == "DRAFT" and "name" in r for r in rows)


@pytest.mark.django_db
def test_charge_types_list_returns_code_name(auth_client):
    ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Фрахт", "sort_order": 10})
    resp = auth_client.get("/api/v1/crm/charge-types/", SERVER_NAME="localhost")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["code"] == "FREIGHT" for r in rows)
