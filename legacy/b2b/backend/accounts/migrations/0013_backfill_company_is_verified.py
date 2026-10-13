"""Backfill Company.is_verified from verification_status — idempotent.

The denormalised is_verified flag drifted from verification_status: prod showed
companies with verification_status_code="L2_VERIFIED" but is_verified=False
(checkup 2026-06-10). verify_company_kyc now keeps them in sync; this one-off
backfill fixes the existing rows. Reverse is a no-op (data correction).
"""

from django.db import migrations

# L2_VERIFIED and above count as "verified". Mirrors LEVEL_RANK in
# accounts.services.kyc; kept inline so the migration is self-contained.
VERIFIED_CODES = ["L2_VERIFIED", "L3_CONTRACTED"]


def backfill(apps, schema_editor):
    Company = apps.get_model("accounts", "Company")
    # Verified status → is_verified True
    Company.objects.filter(verification_status__code__in=VERIFIED_CODES, is_verified=False).update(is_verified=True)
    # Anything below L2 (or no status) that is flagged verified → clear it
    Company.objects.filter(is_verified=True).exclude(verification_status__code__in=VERIFIED_CODES).update(
        is_verified=False
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_customuser_position_alter_company_inn"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=noop),
    ]
