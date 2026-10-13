"""Retire MANUFACTURER (and the unused PLANT) as participant company types.

Roles consolidated to the two marketplace sides — SELLER (SUPPLIER) + BUYER (CLIENT)
— on 2026-06-23. "Manufacturer" is now ONLY an OEM brand reference
(catalog.Manufacturer), not a company role. A manufacturer that sells is a SUPPLIER.

This is data-preserving + idempotent: any company carrying the deprecated type gains
SUPPLIER (so it stays a seller) and loses the deprecated type; WorkspaceRoles whose
applicability pointed at MANUFACTURER are repointed to SUPPLIER; the deprecated
CompanyType rows are deactivated (kept for history). On the current prod/local data
(no MANUFACTURER/PLANT companies) this is a no-op.
"""

from django.db import migrations

_DEPRECATED = ["MANUFACTURER", "PLANT"]


def retire_manufacturer(apps, schema_editor):
    Company = apps.get_model("accounts", "Company")
    CompanyType = apps.get_model("accounts", "CompanyType")
    WorkspaceRole = apps.get_model("accounts", "WorkspaceRole")

    supplier = CompanyType.objects.filter(code="SUPPLIER").first()
    if supplier is None:
        return  # SUPPLIER not seeded yet — nothing safe to migrate to
    deprecated_ids = list(CompanyType.objects.filter(code__in=_DEPRECATED).values_list("id", flat=True))
    if not deprecated_ids:
        return

    # Companies with a deprecated seller type → keep them sellers via SUPPLIER, drop deprecated.
    for company in Company.objects.filter(types__in=deprecated_ids).distinct():
        company.types.add(supplier)
        company.types.remove(*deprecated_ids)

    # WorkspaceRoles applicable to MANUFACTURER/PLANT → applicable to SUPPLIER instead.
    for role in WorkspaceRole.objects.filter(applicable_to_types__in=deprecated_ids).distinct():
        role.applicable_to_types.add(supplier)
        role.applicable_to_types.remove(*deprecated_ids)

    # Deactivate the deprecated types so they're no longer offered as selectable roles.
    CompanyType.objects.filter(code__in=_DEPRECATED).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0017_company_is_verified_index"),
    ]

    operations = [
        migrations.RunPython(retire_manufacturer, migrations.RunPython.noop),
    ]
