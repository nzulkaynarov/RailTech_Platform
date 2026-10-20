"""FIX-41 (F-12): второго ручного курса нет — `exchange_rate_usd_uzs` в system-settings только для чтения из `finance.services.fx`."""

import pytest
from rest_framework.test import APIClient
from sales.tests.helpers_fx import set_rate

from accounts.models import CustomUser
from core.models import SystemSetting

pytestmark = pytest.mark.django_db
URL = "/api/v1/system-settings/"


def _client(*, superuser=False):
    user = CustomUser.objects.create_user(email="u@x.test", username="u@x.test", password=None, is_active=True)
    if superuser:
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_rate_comes_from_exchange_rate_directory():
    set_rate("USD", "12701.5")
    assert _client().get(URL).json()["exchange_rate_usd_uzs"] == "12701.5"


def test_no_fresh_rate_is_null_not_a_made_up_default():
    set_rate("USD", "12701.5", days_ago=30)  # старше лимита — курса нет
    assert _client().get(URL).json()["exchange_rate_usd_uzs"] is None


def test_rate_cannot_be_written_through_settings():
    set_rate("USD", "12701.5")
    response = _client(superuser=True).patch(
        URL, {"exchange_rate_usd_uzs": "99999", "vat_rate": "10.00"}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exchange_rate_usd_uzs"] == "12701.5"
    assert body["vat_rate"] == "10.00"


def test_system_setting_has_no_rate_column():
    assert "exchange_rate_usd_uzs" not in {field.name for field in SystemSetting._meta.get_fields()}
