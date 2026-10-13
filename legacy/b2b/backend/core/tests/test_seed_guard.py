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
def test_core_seed_gives_every_member_a_company_role(settings):
    """Свежий стенд после `make seed` должен быть ПРИГОДЕН для работы ролями.

    Права в `capabilities.permissions` (по ним строится меню, ADR-0005) берутся из
    `CompanyMember.company_role`. Сид его не проставлял: демо-участники приезжали с пустым
    списком прав, а боевые пути — саморегистрация (`submit_profile`) и приглашение
    (`invite_workspace_member`) — роль ставят. Расхождение било по разработчику: локальный
    стенд вёл себя не так, как прод, и прогнать роль глазами было нельзя.
    """
    settings.DEBUG = True
    from accounts.models import CompanyMember

    call_command("core_seed")

    without_role = list(CompanyMember.objects.filter(company_role__isnull=True).values_list("user__email", flat=True))
    assert without_role == [], f"участники без роли компании: {without_role}"


@pytest.mark.django_db
def test_seeded_owner_gets_the_admin_role_and_real_permissions(settings):
    """Владелец компании должен получить системную роль, а не просто «какую-нибудь»."""
    settings.DEBUG = True
    from accounts.constants import WorkspaceRoleCode
    from accounts.models import CompanyMember

    call_command("core_seed")

    owner = CompanyMember.objects.filter(role__code=WorkspaceRoleCode.OWNER).select_related("company_role").first()
    assert owner is not None, "сид не завёл ни одного владельца компании"
    assert owner.company_role is not None
    assert owner.company_role.is_system is True, "владелец получил не системную роль компании"
    assert owner.company_role.permissions, "у роли владельца пустой список прав"
