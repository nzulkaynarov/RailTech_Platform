"""FIX-11 — версия токенов пользователя: отзыв доступа из CRM гасит и уже выданные access-токены."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_remove_companymember_can_buy"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="token_version",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Растёт при отзыве доступа из CRM (sso.revoke): access-токен несёт версию в claim `tv`, "
                "с другой версией — 401 (accounts.authentication)",
                verbose_name="Версия токенов",
            ),
        ),
    ]
