"""Migration 0014: the ВЭД (FOREIGN_TRADE_SPECIALIST) role must be assignable to a
SUPPLIER seller (the seller of record is a SUPPLIER company, not MANUFACTURER), so
the КП approval chain's ВЭД step can have a member.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from accounts.models import Company, CompanyType, CustomUser, WorkspaceRole
from accounts.services.members import add_company_member

pytestmark = pytest.mark.django_db

_MIGRATION = importlib.import_module("accounts.migrations.0014_ved_role_applicable_to_supplier")


def _ensure_types():
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="MANUFACTURER", defaults={"name": "Manufacturer", "sort_order": 30})


def test_migration_widens_ved_to_supplier_and_manufacturer():
    _ensure_types()
    role = WorkspaceRole.objects.get(code="FOREIGN_TRADE_SPECIALIST")
    # Reproduce the MANUFACTURER-only seed state the migration corrects.
    role.applicable_to_types.set(CompanyType.objects.filter(code="MANUFACTURER"))

    _MIGRATION.widen_ved_applicability(django_apps, None)

    role.refresh_from_db()
    assert set(role.applicable_to_types.values_list("code", flat=True)) == {"SUPPLIER", "MANUFACTURER"}


def test_ved_member_can_join_supplier_company():
    _ensure_types()
    _MIGRATION.widen_ved_applicability(django_apps, None)
    company = Company.objects.create(name="Seller Co", inn="7700000099")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="ved@s.test", username="ved_s", password="pw", is_active=True)

    member, err = add_company_member(user, company, "FOREIGN_TRADE_SPECIALIST")
    assert err is None and member is not None
