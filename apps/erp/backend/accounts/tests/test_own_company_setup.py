"""FIX-65: мастер первого запуска — своя компания создаётся из интерфейса, а не из `manage.py shell`."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CustomUser
from core.tenant import own_company, own_company_id

STATUS = "/api/v1/setup/status/"
CREATE = "/api/v1/setup/company/"


def _client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def admin(db):
    return CustomUser.objects.create_superuser(email="root@erp.test", username="root@erp.test", password="x")


@pytest.mark.django_db
def test_clean_database_admin_sees_setup_required(admin):
    data = _client(admin).get(STATUS).json()
    assert data == {"setup_required": True, "can_setup": True}


@pytest.mark.django_db
def test_staff_without_company_sees_required_but_cannot_setup(user_factory):
    user = user_factory(email="e@erp.test", username="e")
    assert _client(user).get(STATUS).json() == {"setup_required": True, "can_setup": False}


@pytest.mark.django_db
def test_admin_creates_own_company_and_becomes_owner(admin):
    client = _client(admin)
    resp = client.post(
        CREATE,
        {"name": "ООО Рейл", "inn": "123456789", "legal_address": "Ташкент", "phone": "+998", "email": "a@b.uz"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    company = Company.objects.get(pk=resp.json()["id"])
    assert own_company_id() == company.pk
    assert own_company() == company
    assert "SUPPLIER" in set(company.types.values_list("code", flat=True))  # CLIENT добавляет сигнал
    member = CompanyMember.objects.get(user=admin, company=company)
    assert member.role.code == "OWNER" and member.is_primary and member.is_active
    assert client.get(STATUS).json() == {"setup_required": False, "can_setup": False}

    from crm.models import ActivityLog

    assert ActivityLog.objects.filter(event_code="admin.company.own_created", entity_id=company.pk, user=admin).exists()


@pytest.mark.django_db
def test_repeat_is_409_and_creates_nothing(admin):
    client = _client(admin)
    assert client.post(CREATE, {"name": "Первая"}, format="json").status_code == 201
    resp = client.post(CREATE, {"name": "Вторая"}, format="json")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "OWN_COMPANY_ALREADY_EXISTS"
    assert Company.objects.count() == 1


@pytest.mark.django_db
def test_existing_own_company_blocks_creation(admin, company_factory, user_factory):
    from accounts.constants import WorkspaceRoleCode
    from accounts.services import add_company_member
    from accounts.testing import make_own_company

    company = make_own_company(company_factory(inn="987654321"))
    staff = user_factory(email="s@erp.test", username="s")
    add_company_member(staff, company, WorkspaceRoleCode.OWNER, is_primary=True)
    resp = _client(admin).post(CREATE, {"name": "Другая"}, format="json")
    assert resp.status_code == 409
    assert _client(admin).get(STATUS).json()["setup_required"] is False


@pytest.mark.django_db
def test_non_superuser_forbidden(user_factory):
    user = user_factory(email="e@erp.test", username="e")
    resp = _client(user).post(CREATE, {"name": "X"}, format="json")
    assert resp.status_code == 403
    assert not Company.objects.exists()


@pytest.mark.django_db
def test_anonymous_unauthorized():
    assert APIClient().post(CREATE, {"name": "X"}, format="json").status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("inn", ["12", "abcdefghi", "1234567890123"])
def test_invalid_inn_is_422_on_field(admin, inn):
    resp = _client(admin).post(CREATE, {"name": "X", "inn": inn}, format="json")
    assert resp.status_code == 422
    assert "inn" in resp.json()
    assert not Company.objects.exists()


@pytest.mark.django_db
def test_name_required_and_email_validated(admin):
    resp = _client(admin).post(CREATE, {"name": "  ", "email": "nope"}, format="json")
    assert resp.status_code == 422
    assert set(resp.json()) == {"name", "email"}


@pytest.mark.django_db
def test_taken_inn_is_field_error(admin, company_factory):
    company_factory(inn="111222333")
    resp = _client(admin).post(CREATE, {"name": "X", "inn": "111222333"}, format="json")
    assert resp.status_code == 422 and "inn" in resp.json()


@pytest.mark.django_db
def test_own_company_id_pointing_elsewhere_rolls_back(admin):
    with override_settings(OWN_COMPANY_ID=999999):
        resp = _client(admin).post(CREATE, {"name": "X"}, format="json")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "OWN_COMPANY_ID_MISMATCH"
    assert not Company.objects.exists()


# --- T2 (волна 11b): миграция ролей при OWN_COMPANY_ID на чистой базе (сброс прода 2026-10-26) ---


@pytest.mark.django_db
def test_role_seed_skips_nonexistent_own_company(caplog):
    """Чистая база + `OWN_COMPANY_ID` на несуществующую компанию: сид миграции accounts/0003 пропускает её
    с записью в лог (раньше — `IntegrityError` внешнего ключа, `migrate` падал)."""
    from django.apps import apps as django_apps
    from django.db import connection

    from accounts.models import CompanyRole
    from core.seeds import backoffice_roles as seed

    with override_settings(OWN_COMPANY_ID=999999), caplog.at_level("WARNING", logger=seed.__name__):
        seed.seed_backoffice_roles(django_apps, None)
        connection.check_constraints()  # отложенные внешние ключи проверяются здесь, а не при коммите

    assert not CompanyRole.objects.exists()
    assert "OWN_COMPANY_ID=999999" in caplog.text


@pytest.mark.django_db
def test_role_seed_still_seeds_existing_configured_company(company_factory):
    from django.apps import apps as django_apps

    from accounts.models import CompanyRole
    from core.seeds import backoffice_roles as seed

    company = company_factory(inn="222333444")
    with override_settings(OWN_COMPANY_ID=company.pk):
        seed.seed_backoffice_roles(django_apps, None)
    assert CompanyRole.objects.filter(company=company, is_system=True).count() == 6


@pytest.mark.django_db
def test_roles_of_own_company_appear_after_first_run_wizard(admin):
    """`OWN_COMPANY_ID=<будущий id>` на чистой базе: миграция ролей не сеет ничего, мастер первого запуска
    создаёт компанию с этим id — и `ensure_default_company_roles` досевает все системные роли."""
    from django.apps import apps as django_apps

    from accounts.constants import BackofficeRoleCode
    from accounts.models import CompanyRole
    from core.seeds import backoffice_roles as seed

    probe = Company.objects.create(name="probe")
    next_id = probe.pk + 1  # следующий id последовательности
    probe.delete()

    with override_settings(OWN_COMPANY_ID=next_id):
        seed.seed_backoffice_roles(django_apps, None)
        assert not CompanyRole.objects.exists()

        resp = _client(admin).post(CREATE, {"name": "ООО Рейл"}, format="json")
        assert resp.status_code == 201, resp.content
        company = Company.objects.get(pk=resp.json()["id"])
        assert company.pk == next_id

    roles = CompanyRole.objects.filter(company=company, is_system=True)
    assert set(roles.values_list("code", flat=True)) == set(BackofficeRoleCode.values)
    member = CompanyMember.objects.get(user=admin, company=company)
    assert set(member.company_roles.values_list("code", flat=True)) == {"HEAD"}
