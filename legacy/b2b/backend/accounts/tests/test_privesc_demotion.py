"""Regression test for migration 0031_demote_overgranted_company_admins (U2 privesc fix).

The migration is a data-fix; pytest runs with --nomigrations, so we import its RunPython
function and exercise it directly against a constructed scenario using the live models.
"""

import importlib

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole

_mig = importlib.import_module("accounts.migrations.0031_demote_overgranted_company_admins")

ADMIN_NAME = "Администратор компании"


def _ws(code):
    return WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})[0]


def _company(name, inn):
    return Company.objects.create(name=name, inn=inn)


def _roles(company):
    """Seed the three CompanyRoles the migration reads for a company."""
    admin = CompanyRole.objects.create(company=company, name=ADMIN_NAME, permissions=["team.manage"], is_system=True)
    observer = CompanyRole.objects.create(company=company, name="Наблюдатель", permissions=[])
    sales = CompanyRole.objects.create(company=company, name="Менеджер по продажам", permissions=["quote.build"])
    return admin, observer, sales


def _member(email, company, ws_code, company_role):
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    return CompanyMember.objects.create(
        user=user, company=company, role=_ws(ws_code), company_role=company_role, is_active=True
    )


def _run():
    from django.apps import apps as global_apps

    _mig.demote_overgranted(global_apps, None)


@pytest.mark.django_db
def test_overgranted_member_is_demoted_owner_kept():
    company = _company("Co1", "1000000001")
    admin, observer, _sales = _roles(company)
    owner = _member("owner@co1.uz", company, "OWNER", admin)  # legit admin
    member = _member("emp@co1.uz", company, "MEMBER", admin)  # over-granted by backfill

    _run()

    owner.refresh_from_db()
    member.refresh_from_db()
    assert owner.company_role_id == admin.id  # OWNER keeps admin
    assert member.company_role_id == observer.id  # MEMBER demoted to Наблюдатель


@pytest.mark.django_db
def test_overgranted_sales_manager_remapped_by_workspace_role():
    company = _company("Co2", "1000000002")
    admin, _observer, sales = _roles(company)
    _member("owner@co2.uz", company, "OWNER", admin)
    sm = _member("sm@co2.uz", company, "SALES_MANAGER", admin)  # over-granted

    _run()

    sm.refresh_from_db()
    assert sm.company_role_id == sales.id  # remapped to «Менеджер по продажам»


@pytest.mark.django_db
def test_sole_admin_non_owner_is_preserved_never_orphan():
    company = _company("Co3", "1000000003")
    admin, _observer, _sales = _roles(company)
    sole = _member("solo@co3.uz", company, "MEMBER", admin)  # the company's ONLY admin

    _run()

    sole.refresh_from_db()
    assert sole.company_role_id == admin.id  # kept — demoting would orphan the company
