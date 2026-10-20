"""FIX-42 (F-4): имя платформы, e-mail поддержки, логотип и домен — общие для ансамбля, ведутся в CRM.

В ERP они только для чтения: PATCH с любым из них — 400 `SHARED_SETTING_READ_ONLY`, остальная часть тела не
применяется. SPA получает адрес CRM (`crm_frontend_url`) для ссылки «Изменить в CRM».
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser
from core.models import SystemSetting

pytestmark = pytest.mark.django_db
URL = "/api/v1/system-settings/"
SHARED = {
    "platform_name": "Чужое имя",
    "support_email": "other@example.test",
    "logo_url": "https://cdn.example.test/logo.png",
    "domain": "other.example.test",
}


def _client(*, superuser=True):
    user = CustomUser.objects.create_user(email="adm@x.test", username="adm@x.test", password=None, is_active=True)
    if superuser:
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("field", sorted(SHARED))
def test_shared_field_cannot_be_written(field):
    before = SystemSetting.load()
    original = getattr(before, field)

    response = _client().patch(URL, {field: SHARED[field]}, format="json")

    assert response.status_code == 400
    assert response.json() == {"detail": "SHARED_SETTING_READ_ONLY", "fields": [field]}
    assert getattr(SystemSetting.objects.get(pk=1), field) == original


def test_shared_field_in_body_rejects_the_whole_patch():
    """Смешанное тело — отказ целиком: НДС из того же запроса не применяется."""
    SystemSetting.load()
    before = SystemSetting.objects.get(pk=1).vat_rate

    response = _client().patch(URL, {"vat_rate": "7.00", **SHARED}, format="json")

    assert response.status_code == 400
    assert response.json()["fields"] == sorted(SHARED)
    assert SystemSetting.objects.get(pk=1).vat_rate == before


def test_unchanged_value_of_shared_field_is_still_rejected():
    """Старый клиент, который шлёт форму целиком, получает отказ, а не молчаливое «сохранено»."""
    current = SystemSetting.load().platform_name

    response = _client().patch(URL, {"platform_name": current, "vat_rate": "9.00"}, format="json")

    assert response.status_code == 400


def test_own_fields_are_still_writable():
    response = _client().patch(URL, {"vat_rate": "9.00", "maintenance_mode": True}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["vat_rate"] == "9.00"
    assert body["maintenance_mode"] is True


def test_non_admin_is_denied_before_the_field_check():
    response = _client(superuser=False).patch(URL, {"platform_name": "x"}, format="json")

    assert response.status_code == 403


def test_get_gives_the_spa_the_crm_address(settings):
    settings.CRM_FRONTEND_URL = "https://crm.example.test"

    body = _client(superuser=False).get(URL).json()

    assert body["crm_frontend_url"] == "https://crm.example.test"
    assert set(SHARED) <= set(body)  # значения по-прежнему видны для просмотра


def test_crm_address_cannot_be_written():
    response = _client().patch(
        URL, {"crm_frontend_url": "https://evil.example.test", "vat_rate": "8.00"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["crm_frontend_url"] != "https://evil.example.test"
