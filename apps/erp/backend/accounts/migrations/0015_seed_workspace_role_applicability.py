"""Re-seed WorkspaceRole.applicable_to_types so the invite role dropdown is
scoped to the company's side.

Bug: migration 0010 set applicable_to_types in the same migrate run that (on a
fresh DB) created the CompanyType rows only later via other seeds, so the
`.set()` matched nothing and every role ended up with an EMPTY applicable_to_types.
The lookup filter (`accounts/views/lookups.py`) then treats empty as "applies to
all", so a SUPPLIER company's OWNER saw BUYER roles (Снабженец) when inviting — the
"do they pick buyer or seller?" confusion.

This migration sets the mapping NOW (CompanyType rows exist) and corrects it for
the current Buyer↔Seller model where the seller is a SUPPLIER company:

  seller roles  -> SUPPLIER, MANUFACTURER (LOGIST also LOGISTICS_PROVIDER)
  buyer roles   -> CLIENT
  universal     -> empty (OWNER/ACCOUNTANT/MEMBER apply to any company)

Idempotent; reverse is a no-op (never auto-narrow a business lookup — Rule 1).
Purely additive to validation: existing members keep their roles; this only scopes
the invite dropdown + the add-member applicability check.
"""

from django.db import migrations

# role code -> applicable CompanyType codes ( [] = universal )
ROLE_APPLICABILITY = {
    "OWNER": [],
    "ACCOUNTANT": [],
    "MEMBER": [],
    "PROCUREMENT_MANAGER": ["CLIENT"],
    "BUYER_MANAGER": ["CLIENT"],
    "SALES_MANAGER": ["SUPPLIER", "MANUFACTURER"],
    "FOREIGN_TRADE_SPECIALIST": ["SUPPLIER", "MANUFACTURER"],
    "CONTRACT_MANAGER": ["SUPPLIER", "MANUFACTURER"],
    "DIRECTOR": ["SUPPLIER", "MANUFACTURER"],
    "LOGIST": ["SUPPLIER", "MANUFACTURER", "LOGISTICS_PROVIDER"],
}


def seed_applicability(apps, schema_editor):
    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")
    CompanyType = apps.get_model("accounts", "CompanyType")
    for role_code, type_codes in ROLE_APPLICABILITY.items():
        role = WorkspaceRole.objects.filter(code=role_code).first()
        if role is None:
            continue
        if not type_codes:
            continue  # universal — leave applicable_to_types empty
        types = list(CompanyType.objects.filter(code__in=type_codes))
        if types:
            role.applicable_to_types.set(types)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_ved_role_applicable_to_supplier"),
    ]

    operations = [
        migrations.RunPython(seed_applicability, reverse_code=noop),
    ]
