"""Schedule the daily CBU FX-rate refresh via django_celery_beat (DatabaseScheduler).

The platform uses the DB scheduler, so the periodic task is seeded here (idempotent) rather
than in settings. Runs every day at 09:30 (CBU publishes rates in the morning). Reverse drops it.
"""

from django.db import migrations


def add_fx_beat(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="9", day_of_week="*", day_of_month="*", month_of_year="*"
    )
    PeriodicTask.objects.get_or_create(
        name="Refresh CBU exchange rates",
        defaults={
            "crontab": schedule,
            "task": "master_data.tasks.refresh_exchange_rates",
            "enabled": True,
            "description": "Ежедневный импорт курсов валют с ЦБ РУз (cbu.uz).",
        },
    )


def remove_fx_beat(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Refresh CBU exchange rates").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("master_data", "0009_exchangerate"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(add_fx_beat, remove_fx_beat)]
