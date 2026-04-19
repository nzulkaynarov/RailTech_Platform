"""
Data migration — register the daily quote-expiry beat task:
  - crm.expire_stale_quotes (05:00 UTC daily)

Idempotent via update_or_create.
"""
from django.db import migrations


def register(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    except LookupError:
        return

    sched, _ = CrontabSchedule.objects.get_or_create(
        minute='0', hour='5', day_of_week='*', day_of_month='*', month_of_year='*',
        defaults={'timezone': 'UTC'},
    )
    PeriodicTask.objects.update_or_create(
        name='crm.expire_stale_quotes (daily)',
        defaults={
            'crontab': sched,
            'task': 'crm.expire_stale_quotes',
            'enabled': True,
            'description': 'Move SENT quotes past valid_until to EXPIRED and notify managers',
        },
    )


def unregister(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    except LookupError:
        return
    PeriodicTask.objects.filter(name='crm.expire_stale_quotes (daily)').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0009_beat_schedule'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(register, reverse_code=unregister),
    ]
