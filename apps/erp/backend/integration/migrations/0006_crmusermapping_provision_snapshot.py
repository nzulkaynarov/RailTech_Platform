from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integration', '0005_pairing_credentials'),
    ]

    operations = [
        migrations.AddField(
            model_name='crmusermapping',
            name='provision_snapshot',
            field=models.JSONField(blank=True, help_text='Роль, права и системные роли из последнего провижининга CRM', null=True, verbose_name='Последний провижининг'),
        ),
    ]
