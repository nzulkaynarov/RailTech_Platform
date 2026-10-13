"""Make the ВЭД (FOREIGN_TRADE_SPECIALIST) role assignable to SUPPLIER companies.

The КП approval chain (документооборот) is a SELLER-team flow and the seller is a
SUPPLIER-type company (RailTech). But migration 0010 seeded
FOREIGN_TRADE_SPECIALIST applicable_to_types = [MANUFACTURER] only, so a pure
SUPPLIER seller could not have a ВЭД member (add_company_member →
WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE), blocking the ВЭД confirm step.

Set it to [SUPPLIER, MANUFACTURER] — works for the current SUPPLIER seller and for
future manufacturer-sellers. Idempotent; reverse is a no-op (never auto-narrow a
business lookup — see Rule 1 in CLAUDE.md).
"""

from django.db import migrations


def widen_ved_applicability(apps, schema_editor):
    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")
    CompanyType = apps.get_model("accounts", "CompanyType")
    role = WorkspaceRole.objects.filter(code="FOREIGN_TRADE_SPECIALIST").first()
    if role is None:
        return
    types = list(CompanyType.objects.filter(code__in=["SUPPLIER", "MANUFACTURER"]))
    if types:
        role.applicable_to_types.set(types)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_backfill_company_is_verified"),
    ]

    operations = [
        migrations.RunPython(widen_ved_applicability, reverse_code=noop),
    ]
