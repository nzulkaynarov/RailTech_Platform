"""FIX-13 — в ERP входят только сотрудники (ORCHESTRATOR §3.1, apps/erp/CLAUDE.md §2 п.1).

Участник компании-клиента, у которого есть пароль, получает 403 `STAFF_ONLY` ДО выпуска токенов:
ни access, ни refresh, ни строки в `OutstandingToken`. Неверный пароль по-прежнему 401 (и считается
в блокировке); сотрудник своей компании и администратор входят.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/v1/auth/token/"
HASLO = "Str0ng-Pass-FIX13"


@pytest.fixture
def world(db):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client"})[0]
    workspace = WorkspaceRole.objects.get(code="MEMBER")
    own = Company.objects.create(name="Своя компания", inn="400000001")
    own.types.add(supplier)
    client_company = Company.objects.create(name="Клиент", inn="400000002")
    client_company.types.add(client_type)

    def user(email, company=None, **extra):
        created = CustomUser.objects.create_user(email=email, username=email, password=HASLO, **extra)
        if company is not None:
            CompanyMember.objects.create(user=created, company=company, role=workspace, is_primary=True)
        return created

    return {
        "staff": user("staff@own.example", own),
        "client_member": user("member@client.example", client_company),
        "no_company": user("nobody@example.test"),
        "superuser": CustomUser.objects.create_superuser(email="root@erp.example", username="root", password=HASLO),
    }


def _login(email, password=HASLO):
    client = APIClient()
    client.raise_request_exception = False
    return client.post(LOGIN_URL, {"email": email, "password": password}, format="json")


def test_staff_member_logs_in(world):
    response = _login("staff@own.example")
    assert response.status_code == 200
    assert "access" in response.data


def test_superuser_logs_in_without_company(world):
    assert _login("root@erp.example").status_code == 200


def test_client_company_member_gets_staff_only(world):
    response = _login("member@client.example")
    assert response.status_code == 403
    assert response.data == {"detail": "STAFF_ONLY"}
    assert "access" not in response.data and "refresh_token" not in response.cookies


def test_client_company_member_gets_no_tokens_issued(world):
    _login("member@client.example")
    assert not OutstandingToken.objects.filter(user=world["client_member"]).exists()


def test_user_without_active_membership_in_own_company_gets_staff_only(world):
    assert _login("nobody@example.test").data == {"detail": "STAFF_ONLY"}
    CompanyMember.objects.filter(user=world["staff"]).update(is_active=False)
    assert _login("staff@own.example").data == {"detail": "STAFF_ONLY"}


def test_wrong_password_is_still_401_not_staff_only(world):
    assert _login("member@client.example", "wrong-password").status_code == 401


def test_client_with_two_factor_is_refused_before_the_ticket(world):
    CustomUser.objects.filter(pk=world["client_member"].pk).update(is_2fa_enabled=True)
    response = _login("member@client.example")
    assert response.status_code == 403
    assert "temp_token" not in response.data
