"""FIX-14 (аудит P-9): токены сессий и magic-link хранятся как SHA-256-хеш, не открытым текстом."""

import hashlib

from django.db import migrations, models


def hash_existing_tokens(apps, schema_editor):
    """Переносит открытые токены в хеши: выданные cookie и ссылки продолжают работать, но в базе их уже нет."""
    for model_name in ("PortalSession", "MagicLinkToken"):
        model = apps.get_model("portal", model_name)
        for pk, raw in model.objects.values_list("pk", "token_hash").iterator():
            model.objects.filter(pk=pk).update(token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest())


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0002_portalupload_deal_portalrequestline_and_more"),
    ]

    operations = [
        migrations.RenameField(model_name="portalsession", old_name="token", new_name="token_hash"),
        migrations.RenameField(model_name="magiclinktoken", old_name="token", new_name="token_hash"),
        migrations.AlterField(
            model_name="portalsession",
            name="token_hash",
            field=models.CharField(
                help_text="Сырой токен хранится только в cookie клиента",
                max_length=64,
                unique=True,
                verbose_name="SHA-256 токена сессии",
            ),
        ),
        migrations.AlterField(
            model_name="magiclinktoken",
            name="token_hash",
            field=models.CharField(
                help_text="Сырой токен есть только в письме",
                max_length=64,
                unique=True,
                verbose_name="SHA-256 токена ссылки",
            ),
        ),
        migrations.AddField(
            model_name="magiclinktoken",
            name="purpose",
            field=models.CharField(
                choices=[("login", "Вход по запросу клиента"), ("invite", "Приглашение из ERP")],
                default="login",
                max_length=10,
                verbose_name="Назначение",
            ),
        ),
        # Обратно хеш в открытый токен не превратить: откат оставляет хеши, старые токены перестанут подходить.
        migrations.RunPython(hash_existing_tokens, migrations.RunPython.noop),
    ]
