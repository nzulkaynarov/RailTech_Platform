"""SEC-03: core_seed creates DEMO login accounts with a known password, so it must refuse
to run against a non-DEBUG (prod-like) environment unless explicitly forced."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_core_seed_refuses_when_debug_false(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="Refusing to run with DEBUG=False"):
        call_command("core_seed")


@pytest.mark.django_db
def test_core_seed_gives_every_staff_member_a_backoffice_role(settings):
    """Свежий стенд после `make seed` должен быть ПРИГОДЕН для работы ролями (M1-ERP-05).

    Права в `capabilities.permissions` (по ним строится меню) — объединение ролей бэк-офиса
    сотрудника своей компании. Сид выдаёт стартовые роли тем же сервисом, что приглашение
    (`grant_default_roles`); покупательский демо-аккаунт ролей бэк-офиса не получает.
    """
    settings.DEBUG = True
    from accounts.models import CompanyMember
    from core.tenant import own_company_id

    call_command("core_seed")

    own_id = own_company_id()
    assert own_id is not None, "сид не завёл свою компанию с сотрудниками"
    staff = CompanyMember.objects.filter(company_id=own_id)
    without_role = list(staff.filter(company_roles__isnull=True).values_list("user__email", flat=True))
    assert without_role == [], f"сотрудники без роли бэк-офиса: {without_role}"
    assert not CompanyMember.objects.exclude(company_id=own_id).filter(company_roles__isnull=False).exists()


@pytest.mark.django_db
def test_seeded_owner_gets_the_head_role_and_real_permissions(settings):
    """Владелец своей компании получает системную роль «Руководитель» со всеми правами."""
    settings.DEBUG = True
    from accounts.constants import ALL_PERMISSIONS, WorkspaceRoleCode
    from accounts.models import CompanyMember
    from accounts.services.permissions import staff_permissions
    from core.tenant import own_company_id

    call_command("core_seed")

    owner = CompanyMember.objects.filter(company_id=own_company_id(), role__code=WorkspaceRoleCode.OWNER).first()
    assert owner is not None, "сид не завёл владельца своей компании"
    assert list(owner.company_roles.values_list("code", flat=True)) == ["HEAD"]
    assert staff_permissions(owner.user) == frozenset(ALL_PERMISSIONS)
