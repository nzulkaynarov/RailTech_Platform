"""FIX-63 (D-10) — пометка «роль выдана из CRM» для системных ролей, пришедших в `role_codes` провижининга."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_split_sso_full_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymember",
            name="crm_granted_roles",
            field=models.ManyToManyField(
                blank=True,
                help_text="Системные роли, которые CRM выдала провижинингом (`role_codes`); снимаются тоже из CRM",
                related_name="crm_granted_members",
                to="accounts.companyrole",
                verbose_name="Роли, выданные из CRM",
            ),
        ),
    ]
