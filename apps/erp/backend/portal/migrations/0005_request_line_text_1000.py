# Строка запроса клиента — до 1000 знаков по контракту портала (`RequestLineIn.text`, FIX-23): прежние 500 знаков
# давали 500 Server Error на корректном вводе.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0004_portal_request_summary'),
    ]

    operations = [
        migrations.AlterField(
            model_name='portalrequestline',
            name='text',
            field=models.CharField(max_length=1000, verbose_name='Наименование/описание'),
        ),
    ]
