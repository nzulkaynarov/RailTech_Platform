from django.db import migrations, models


def seed_bank_codes_beat(apps, schema_editor):
    """Задача Beat ежемесячной загрузки кодов банков в существующих базах; новые получают её из сида Beat."""
    from core.seeds.beat import seed_bank_codes_task

    seed_bank_codes_task(apps)


def drop_bank_codes_beat(apps, schema_editor):
    from core.seeds.beat import BANK_CODES_TASK

    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name=BANK_CODES_TASK).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_telegram_bot_projection'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='bank',
            name='source',
            field=models.CharField(blank=True, default='', max_length=16, verbose_name='Источник'),
        ),
        migrations.AddField(
            model_name='bank',
            name='synced_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Обновлено из источника'),
        ),
        migrations.AddField(
            model_name='bank',
            name='in_source',
            field=models.BooleanField(default=True, verbose_name='Есть в источнике'),
        ),
        migrations.AddField(
            model_name='bank',
            name='manual_fields',
            field=models.JSONField(blank=True, default=list, verbose_name='Поля, изменённые руками'),
        ),
        migrations.RunPython(seed_bank_codes_beat, drop_bank_codes_beat),
    ]
