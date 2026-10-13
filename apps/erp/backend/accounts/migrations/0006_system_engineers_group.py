"""
Create the `system_engineers` Django group used to gate access to Django Unfold admin.

Per ADR-0001:
- Unfold admin = engineering / DBA inspection tool
- React admin = business operations
- Only users in this group (plus superusers) should be granted is_staff = True
- This migration creates the group with no specific permissions; permissions
  are inherited from is_staff + the per-model has_*_permission overrides in admin.py
"""
from django.db import migrations


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="system_engineers")


def remove_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="system_engineers").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_kycdocument_options_alter_company_bank_account_and_more"),
    ]

    operations = [
        migrations.RunPython(create_group, reverse_code=remove_group),
    ]
