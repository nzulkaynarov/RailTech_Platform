from django.db import migrations, models


class Migration(migrations.Migration):
    """FIX-54 (P-18): новый контакт по умолчанию без права действовать; существующие строки не меняются."""

    dependencies = [
        ("parties", "0006_remove_companysettings_notify_client_on_schedule_shift"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contact",
            name="can_act",
            field=models.BooleanField(
                default=False,
                help_text="Право принимать КП, подписывать договоры и принимать акты",
                verbose_name="Право действовать",
            ),
        ),
    ]
