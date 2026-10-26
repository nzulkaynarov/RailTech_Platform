"""W13-A3: ставку НДС платформы меняет держатель права `settings.edit` (раздел Платформы «Компания») или администратор.

Остальные поля (`maintenance_mode`, `is_two_factor_required`) закрывают вход всем — их по-прежнему меняет только
администратор (`is_superuser`); без права `settings.edit` отказ на любом поле.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from core.models import SystemSetting

pytestmark = pytest.mark.django_db
URL = "/api/v1/system-settings/"


def _member(email: str, permissions: list[str]) -> CustomUser:
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    company = Company.objects.create(name=f"ООО {email}", inn="9700000001")
    company.types.add(supplier_type)
    workspace_role, _ = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
    )
    role = CompanyRole.objects.create(company=company, name=f"Роль {email}", permissions=permissions)
    user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=workspace_role,
        company_roles=[role],
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_settings_editor_changes_vat_rate():
    response = _member("editor@w13.test", ["settings.edit"]).patch(URL, {"vat_rate": "13.00"}, format="json")

    assert response.status_code == 200
    assert SystemSetting.objects.get(pk=1).vat_rate == 13


@pytest.mark.parametrize(
    "body",
    [{"maintenance_mode": True}, {"is_two_factor_required": True}, {"vat_rate": "9.00", "maintenance_mode": True}],
)
def test_settings_editor_cannot_touch_lockout_switches(body):
    SystemSetting.load()
    before = SystemSetting.objects.get(pk=1).vat_rate

    response = _member("editor2@w13.test", ["settings.edit"]).patch(URL, body, format="json")

    assert response.status_code == 403
    assert response.json()["detail"] == "PLATFORM_ADMIN_REQUIRED"
    assert SystemSetting.objects.get(pk=1).vat_rate == before


def test_member_without_settings_edit_is_denied():
    response = _member("plain@w13.test", ["catalog.manage"]).patch(URL, {"vat_rate": "13.00"}, format="json")

    assert response.status_code == 403
