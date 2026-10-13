"""Недельный автосинк классификатора ТН ВЭД через django_celery_beat (DatabaseScheduler).

Периодическая задача сеется здесь (идемпотентно), как и FX-график в 0010. Номенклатура
меняется редко (национальные редакции — считанные разы в год), но выгрузка получасовая,
поэтому — раз в неделю, в ночь на понедельник 03:00, когда очередь `imports` свободна.
Reverse удаляет задачу.
"""

from django.db import migrations


def add_tnved_beat(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="1", day_of_month="*", month_of_year="*"
    )
    PeriodicTask.objects.get_or_create(
        name="Sync TN VED classifier",
        defaults={
            "crontab": schedule,
            "task": "master_data.tasks.refresh_tnved_codes",
            "enabled": True,
            "description": "Еженедельная синхронизация справочника ТН ВЭД с tarif.customs.uz (ГТК РУз).",
        },
    )


def remove_tnved_beat(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Sync TN VED classifier").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("master_data", "0012_hs_code_units"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(add_tnved_beat, remove_tnved_beat)]
