"""Migration 0014: the ВЭД (FOREIGN_TRADE_SPECIALIST) role must be assignable to a
SUPPLIER seller (the seller of record is a SUPPLIER company, not MANUFACTURER), so
the КП approval chain's ВЭД step can have a member.
"""

from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from accounts.models import Company, CompanyType, CustomUser, WorkspaceRole
from accounts.services.members import add_company_member
from core.seeds.accounts import widen_ved_applicability

pytestmark = pytest.mark.django_db

_MIGRATION = SimpleNamespace(widen_ved_applicability=widen_ved_applicability)


@pytest.fixture
def lookups(db):
    # The suite runs with --nomigrations (pyproject addopts), so the schema is built
    # from models and RunPython seed migrations DON'T run — migration-seeded lookups
    # (WorkspaceRole/CompanyType) are absent. Create what we need, like every other
    # test here; never rely on seeded rows.
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="MANUFACTURER", defaults={"name": "Manufacturer", "sort_order": 30})
    WorkspaceRole.objects.get_or_create(code="FOREIGN_TRADE_SPECIALIST", defaults={"name": "ВЭД", "sort_order": 60})


def test_migration_widens_ved_to_supplier_and_manufacturer(lookups):
    role = WorkspaceRole.objects.get(code="FOREIGN_TRADE_SPECIALIST")
    # Reproduce the MANUFACTURER-only seed state the migration corrects.
    role.applicable_to_types.set(CompanyType.objects.filter(code="MANUFACTURER"))

    _MIGRATION.widen_ved_applicability(django_apps, None)

    role.refresh_from_db()
    assert set(role.applicable_to_types.values_list("code", flat=True)) == {"SUPPLIER", "MANUFACTURER"}


def test_ved_member_can_join_supplier_company(lookups):
    _MIGRATION.widen_ved_applicability(django_apps, None)
    company = Company.objects.create(name="Seller Co", inn="7700000099")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="ved@s.test", username="ved_s", password="pw", is_active=True)

    member, err = add_company_member(user, company, "FOREIGN_TRADE_SPECIALIST")
    assert err is None and member is not None
