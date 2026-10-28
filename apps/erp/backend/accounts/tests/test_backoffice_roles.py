"""Роли бэк-офиса M1-ERP-05: шаблоны → права (таблица), объединение ролей, нет фолбэка из
должности и флагов, назначение нескольких ролей, `/me`, миграция старых ролей."""

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from accounts.constants import ALL_PERMISSIONS, ROLE_TEMPLATES, BackofficeRoleCode
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from accounts.services.permissions import member_has_permission, staff_permissions
from accounts.services.roles import ensure_default_company_roles, set_member_roles
from core.seeds import backoffice_roles as frozen

# Документированная матрица (CONVENTIONS.md §6). Меняется только вместе с документом.
EXPECTED_TEMPLATES = {
    "CALCULATION": {
        "deal.manage",
        "quote.build",
        "quote.edit_pricing",
        "quote.view_cost_margin",
        "quote.send",
        "quote.review",
        "quote.visa_goods",
        "quote.visa_services",
        "contract.manage",
    },
    "CATALOG_SUPPLY": {"catalog.manage", "catalog.publish", "supply.manage", "quote.view_cost_margin"},
    "FULFILLMENT": {"fulfillment.manage", "fulfillment.act"},
    "FINANCE": {
        "finance.view",
        "finance.invoice",
        "finance.payment",
        "finance.rates",
        "quote.view_cost_margin",
        "data.export",
    },
    "HEAD": set(ALL_PERMISSIONS),
    "VIEWER": set(),
}


@pytest.mark.parametrize("code", list(EXPECTED_TEMPLATES))
def test_role_template_table(code):
    assert set(ROLE_TEMPLATES[code]) == EXPECTED_TEMPLATES[code]


def test_templates_cover_business_roles_and_prefixes():
    assert set(ROLE_TEMPLATES) == set(BackofficeRoleCode.values)
    prefixes = {code.split(".")[0] for code in ALL_PERMISSIONS}
    assert prefixes == {
        "deal",
        "quote",
        "contract",
        "catalog",
        "supply",
        "fulfillment",
        "finance",
        "settings",
        "team",
        "data",
    }
    # Каждое право бэк-офиса принадлежит хотя бы одной роли помимо «Руководителя».
    granted = set().union(*(set(p) for c, p in ROLE_TEMPLATES.items() if c != "HEAD"))
    assert set(ALL_PERMISSIONS) - granted <= {"deal.assign", "contract.sign"} | {
        "settings.edit",
        "settings.charge_templates",
        "team.manage",
    }


def test_frozen_migration_table_matches_code():
    # Каталог и шаблоны = таблица миграции 0003 + добавки миграций 0004 (M1-ERP-08, `finance.rates`), 0011 (D2-1,
    # визы расчёта по типу позиции) и 0012 (D2-4, `finance.view`).
    added = frozen.ADDED_0004 + frozen.ADDED_0011 + frozen.ADDED_0012
    assert set(frozen.ALL) | set(added) == set(ALL_PERMISSIONS)
    assert len(frozen.ALL) + len(added) == len(ALL_PERMISSIONS)
    assert {
        code: set(perms)
        | set(frozen.ROLE_GRANTS_0004.get(code, []))
        | set(frozen.ROLE_GRANTS_0011.get(code, []))
        | set(frozen.ROLE_GRANTS_0012.get(code, []))
        for code, _name, perms in frozen.BACKOFFICE_ROLES
    } == {code: set(perms) for code, perms in ROLE_TEMPLATES.items()}
    assert [name for _c, name, _p in frozen.BACKOFFICE_ROLES] == [label for _v, label in BackofficeRoleCode.choices]
    # Волна 12 (EDS-03): каталог после accounts/0010 — каталог кода без виз D2-1 и `finance.view`;
    # после 0012 — ровно каталог кода.
    assert set(frozen.CATALOG_0010) == set(ALL_PERMISSIONS) - set(frozen.ADDED_0011) - set(frozen.ADDED_0012)
    assert set(frozen.CATALOG_0011) == set(ALL_PERMISSIONS) - set(frozen.ADDED_0012)
    assert set(frozen.CATALOG_0012) == set(ALL_PERMISSIONS)


def test_migration_0010_prunes_codes_outside_the_catalog_from_roles_and_snapshots(db):
    """Код финального утверждения КП (и любой код вне каталога) снимается с ролей и снимков провижининга CRM."""
    from integration.models import CrmUserMapping

    company = Company.objects.create(name="ООО Своя", inn="7700000999")
    stale = "quote.final_" + "approval_v0"  # код вне каталога (снятый волной 12 — того же рода)
    role = CompanyRole.objects.create(company=company, name="Руководитель+", permissions=["quote.review", stale])
    user = CustomUser.objects.create_user(email="ceo@own.test", username="ceo@own.test", password=None)
    mapping = CrmUserMapping.objects.create(
        crm_user_id=77, user=user, provision_snapshot={"role": "backoffice", "permissions": ["deal.manage", stale]}
    )

    frozen.prune_unknown_permissions(django_apps, None)
    frozen.prune_unknown_snapshot_permissions(django_apps, None)

    role.refresh_from_db()
    mapping.refresh_from_db()
    assert role.permissions == ["quote.review"]
    assert mapping.provision_snapshot == {"role": "backoffice", "permissions": ["deal.manage"]}


@pytest.fixture
def own(db):
    company = Company.objects.create(name="Своя", inn="400000001")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "S"})[0])
    return company


def _member(company, email, *, workspace="MEMBER", can_sell=True):
    user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
    membership = CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace),
        is_primary=True,
        can_sell=can_sell,
    )
    return user, membership


@pytest.mark.django_db
def test_seeded_system_roles_are_immutable_templates(own):
    roles = ensure_default_company_roles(own)
    assert set(roles) == set(BackofficeRoleCode.values)
    for code, role in roles.items():
        assert role.is_system and role.code == code and set(role.permissions) == EXPECTED_TEMPLATES[code]
    ensure_default_company_roles(own)
    assert CompanyRole.objects.filter(company=own).count() == len(BackofficeRoleCode.values)


@pytest.mark.django_db
def test_system_role_drifted_permissions_are_restored(own):
    role = ensure_default_company_roles(own)["FINANCE"]
    CompanyRole.objects.filter(pk=role.pk).update(permissions=["team.manage"])
    ensure_default_company_roles(own)
    role.refresh_from_db()
    assert set(role.permissions) == EXPECTED_TEMPLATES["FINANCE"]


@pytest.mark.django_db
def test_permissions_are_the_union_of_roles(own):
    roles = ensure_default_company_roles(own)
    user, membership = _member(own, "two@own.example")
    membership.company_roles.add(roles["FULFILLMENT"], roles["FINANCE"])
    assert staff_permissions(user) == frozenset(EXPECTED_TEMPLATES["FULFILLMENT"] | EXPECTED_TEMPLATES["FINANCE"])
    assert member_has_permission(user, own.id, "fulfillment.act")
    assert member_has_permission(user, own.id, "finance.payment")
    assert not member_has_permission(user, own.id, "quote.build")


@pytest.mark.django_db
def test_no_role_no_permission_even_for_owner_with_flags(own):
    """Снятый фолбэк: должность OWNER и флаги can_sell/can_buy прав сотруднику не дают."""
    user, _membership = _member(own, "owner@own.example", workspace="OWNER", can_sell=True)
    assert staff_permissions(user) == frozenset()
    for code in ALL_PERMISSIONS:
        assert not member_has_permission(user, own.id, code)


@pytest.mark.django_db
def test_inactive_membership_loses_permissions(own):
    roles = ensure_default_company_roles(own)
    user, membership = _member(own, "gone@own.example")
    membership.company_roles.add(roles["HEAD"])
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    assert staff_permissions(user) == frozenset()


@pytest.mark.django_db
def test_superuser_has_every_permission(own):
    admin = CustomUser.objects.create_superuser(email="root@own.example", username="root", password=None)
    assert staff_permissions(admin) == frozenset(ALL_PERMISSIONS)


@pytest.mark.django_db
def test_unknown_codes_in_a_role_are_ignored(own):
    user, membership = _member(own, "legacy@own.example")
    legacy = CompanyRole.objects.create(company=own, name="Старая", permissions=["payment.record", "quote.build"])
    membership.company_roles.add(legacy)
    assert staff_permissions(user) == frozenset({"quote.build"})


@pytest.mark.django_db
def test_set_member_roles_replaces_the_set(own):
    roles = ensure_default_company_roles(own)
    head, head_membership = _member(own, "head@own.example")
    head_membership.company_roles.add(roles["HEAD"])
    _worker, membership = _member(own, "worker@own.example")
    member, err = set_member_roles(head, membership.id, [roles["CALCULATION"].id, roles["FINANCE"].id])
    assert err is None
    assert set(member.company_roles.values_list("code", flat=True)) == {"CALCULATION", "FINANCE"}
    member, err = set_member_roles(head, membership.id, [])
    assert err is None and not member.company_roles.exists()


@pytest.mark.django_db
def test_set_member_roles_guards(own):
    roles = ensure_default_company_roles(own)
    head, head_membership = _member(own, "head2@own.example")
    head_membership.company_roles.add(roles["HEAD"])
    plain, plain_membership = _member(own, "plain@own.example")
    plain_membership.company_roles.add(roles["CALCULATION"])
    assert set_member_roles(plain, head_membership.id, [])[1] == "ONLY_TEAM_MANAGER_CAN_MANAGE_ROLES"
    assert set_member_roles(head, head_membership.id, [roles["VIEWER"].id])[1] == "CANNOT_DROP_OWN_TEAM_MANAGE"
    assert set_member_roles(head, plain_membership.id, "x")[1] == "ROLE_IDS_REQUIRED"
    assert set_member_roles(head, plain_membership.id, [999999])[1] == "ROLE_NOT_FOUND"
    other = Company.objects.create(name="Чужая", inn="400000009")
    foreign = CompanyRole.objects.create(company=other, name="Чужая роль", permissions=[])
    assert set_member_roles(head, plain_membership.id, [foreign.id])[1] == "ROLE_COMPANY_MISMATCH"


@pytest.mark.django_db
def test_assign_api_and_me_capabilities(own):
    roles = ensure_default_company_roles(own)
    head, head_membership = _member(own, "head3@own.example")
    head_membership.company_roles.add(roles["HEAD"])
    worker, membership = _member(own, "worker3@own.example")
    client = APIClient()
    client.force_authenticate(head)
    response = client.post(
        "/api/v1/accounts/company-roles/assign/",
        {"member_id": membership.id, "role_ids": [roles["CATALOG_SUPPLY"].id, roles["FULFILLMENT"].id]},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["role_ids"] == sorted([roles["CATALOG_SUPPLY"].id, roles["FULFILLMENT"].id])

    client.force_authenticate(worker)
    me = client.get("/api/v1/accounts/users/me/").json()
    assert (
        set(me["capabilities"]["permissions"])
        == EXPECTED_TEMPLATES["CATALOG_SUPPLY"] | EXPECTED_TEMPLATES["FULFILLMENT"]
    )
    assert "can_sell" not in me and "can_buy" not in me
    assert "can_sell" not in me["capabilities"]


@pytest.mark.django_db
def test_roles_list_seeds_templates_for_staff(own):
    user, _membership = _member(own, "viewer@own.example")
    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/v1/accounts/company-roles/")
    assert response.status_code == 200
    payload = response.json()
    rows = payload["results"] if isinstance(payload, dict) else payload
    assert {row["code"] for row in rows if row["is_system"]} == set(BackofficeRoleCode.values)


@pytest.mark.django_db
def test_invite_grants_starting_roles_by_position(own):
    from accounts.services.members import invite_workspace_member

    user, err = invite_workspace_member(own, "logist@own.example", "LOGIST")
    assert err is None
    membership = user.memberships.get(company=own)
    assert list(membership.company_roles.values_list("code", flat=True)) == ["FULFILLMENT"]


@pytest.mark.django_db
def test_migration_maps_marketplace_roles_to_backoffice_roles(own):
    """`core.seeds.backoffice_roles.seed_backoffice_roles` (миграция accounts/0003) на живых моделях:
    старые шаблоны → новые роли, старые коды прав → новые, участники без роли → по должности."""
    admin_role = CompanyRole.objects.create(company=own, name="Администратор компании", is_system=True)
    sales_role = CompanyRole.objects.create(company=own, name="Менеджер по продажам", permissions=["quote.build"])
    custom = CompanyRole.objects.create(company=own, name="Касса", permissions=["payment.record"])
    _u1, admin_member = _member(own, "a@own.example")
    admin_member.company_roles.add(admin_role)
    _u2, sales_member = _member(own, "s@own.example")
    sales_member.company_roles.add(sales_role)
    _u3, cashier = _member(own, "c@own.example")
    cashier.company_roles.add(custom)
    _u4, accountant = _member(own, "acc@own.example", workspace="ACCOUNTANT")

    frozen.seed_backoffice_roles(django_apps, None)

    assert set(admin_member.company_roles.values_list("code", flat=True)) == {"HEAD"}
    assert set(sales_member.company_roles.values_list("code", flat=True)) == {"CALCULATION", "CATALOG_SUPPLY"}
    custom.refresh_from_db()
    assert custom.permissions == ["finance.payment"]
    assert set(accountant.company_roles.values_list("code", flat=True)) == {"FINANCE"}
    assert not CompanyRole.objects.filter(company=own, name__in=["Администратор компании", "Менеджер по продажам"])
