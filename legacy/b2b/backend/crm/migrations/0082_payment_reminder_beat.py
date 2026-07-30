"""Ежедневная рассылка напоминаний о просроченных счетах (G3).

Задача НЕ проставляет статус OVERDUE: просрочка остаётся вычисляемой (эталоны её не хранят —
у Stripe `past_due` вообще не статус счёта). Задача только шлёт по ОДНОМУ письму на счёт и
отмечает факт отправки, чтобы не повторяться ежедневно.

Время выбрано 05:00 UTC — после `check_overdue_deliveries` (04:00), чтобы дневные рассылки
не стартовали одновременно.

Идемпотентно: `update_or_create`.
"""

from django.db import migrations


def register(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return  # django_celery_beat не установлен — нечего регистрировать

    schedule = CrontabSchedule.objects.filter(
        minute="0", hour="5", day_of_week="*", day_of_month="*", month_of_year="*"
    ).first()
    if schedule is None:
        schedule = CrontabSchedule.objects.create(
            minute="0",
            hour="5",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone="UTC",
        )
    PeriodicTask.objects.update_or_create(
        name="crm.send_payment_reminders (daily)",
        defaults={
            "crontab": schedule,
            "task": "crm.send_payment_reminders",
            "enabled": True,
            "description": "Одно письмо-напоминание по каждому неоплаченному счёту после срока",
        },
    )


def unregister(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name="crm.send_payment_reminders (daily)").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0081_payment_reminder_and_terms"),
    ]

    operations = [
        migrations.RunPython(register, unregister),
    ]
