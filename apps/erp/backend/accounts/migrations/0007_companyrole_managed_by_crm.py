"""FIX-55 (D-15) — признак роли, которую ведёт провижининг из CRM («CRM Sync: <e-mail>»)."""

from django.db import migrations, models


def mark_existing_sync_roles(apps, schema_editor):
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    CompanyRole.objects.filter(name__startswith="CRM Sync: ", is_system=False).update(managed_by_crm=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_customuser_token_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyrole",
            name="managed_by_crm",
            field=models.BooleanField(
                default=False,
                help_text="Роль «CRM Sync: <e-mail>» ведёт провижининг из CRM (integration.services.provision): права и состав "
                "приходят из CRM, в «Настройках → Команда» её нельзя назначить, изменить или снять",
                verbose_name="Управляется CRM",
            ),
        ),
        migrations.RunPython(mark_existing_sync_roles, migrations.RunPython.noop),
    ]
