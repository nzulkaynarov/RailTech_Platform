"""Re-assert the canonical SystemRole set = {ADMIN, USER}.

Migration 0010 narrowed SystemRole to ADMIN/USER (ADR-0002), but legacy rows
(GUEST / CLIENT / EMPLOYEE / ACCOUNT_MANAGER / SALES_MANAGER) lingered in some DBs
seeded by core/0002 before that cleanup — and they leaked into the React admin Users
filter (sourced live from /accounts/system-roles/). This idempotently re-applies the
cleanup everywhere. core_seed already seeds only {ADMIN, USER}.
"""

from django.db import migrations

CANONICAL = ["ADMIN", "USER"]


def purge_retired_system_roles(apps, schema_editor):
    SystemRole = apps.get_model("accounts", "SystemRole")
    CustomUser = apps.get_model("accounts", "CustomUser")
    user_role = SystemRole.objects.filter(code="USER").first()
    if user_role:
        # Defensive: move any user still on a retired role to USER before deleting.
        CustomUser.objects.exclude(role__code__in=CANONICAL).exclude(role__isnull=True).update(role=user_role)
    SystemRole.objects.exclude(code__in=CANONICAL).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0018_retire_manufacturer_role")]
    operations = [migrations.RunPython(purge_retired_system_roles, migrations.RunPython.noop)]
