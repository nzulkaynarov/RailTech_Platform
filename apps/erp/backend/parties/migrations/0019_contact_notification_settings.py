# Generated manually for J3 (Notification Preferences Matrix, ADR-0023)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0018_contact_is_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="notification_settings",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Матрица группа событий -> каналы {email: bool, telegram: bool} (J3, ADR-0023)",
                verbose_name="Настройки каналов уведомлений",
            ),
        ),
    ]

