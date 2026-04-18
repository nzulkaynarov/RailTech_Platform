"""
Data migration — register daily beat tasks:
  - accounts.expire_subscriptions   (03:00 UTC daily)
  - crm.check_overdue_deliveries    (04:00 UTC daily)

Idempotent: uses get_or_create.
"""
from django.db import migrations


def register_beat_tasks(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    except LookupError:
        return  # django_celery_beat not installed — nothing to do

    def ensure_crontab(hour: str):
        qs = CrontabSchedule.objects.filter(
            minute='0', hour=hour, day_of_week='*', day_of_month='*', month_of_year='*',
        )
        existing = qs.first()
        if existing is not None:
            return existing
        return CrontabSchedule.objects.create(
            minute='0', hour=hour, day_of_week='*', day_of_month='*', month_of_year='*',
            timezone='UTC',
        )

    sched_03 = ensure_crontab('3')
    sched_04 = ensure_crontab('4')
    PeriodicTask.objects.update_or_create(
        name='accounts.expire_subscriptions (daily)',
        defaults={
            'crontab': sched_03,
            'task': 'accounts.expire_subscriptions',
            'enabled': True,
            'description': 'Demote expired TRIAL/ACTIVE subs to PAST_DUE, then SUSPENDED after 14 days',
        },
    )
    PeriodicTask.objects.update_or_create(
        name='crm.check_overdue_deliveries (daily)',
        defaults={
            'crontab': sched_04,
            'task': 'crm.check_overdue_deliveries',
            'enabled': True,
            'description': 'Warn managers about fulfillments past expected_delivery_date',
        },
    )


def unregister(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    except LookupError:
        return
    PeriodicTask.objects.filter(
        name__in=[
            'accounts.expire_subscriptions (daily)',
            'crm.check_overdue_deliveries (daily)',
        ],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0008_contract_fulfillment_invoice_act_invoiceitem_payment_and_more'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(register_beat_tasks, reverse_code=unregister),
    ]
