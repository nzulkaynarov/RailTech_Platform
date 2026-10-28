"""Расписание: ежедневное уведомление о просроченных заказах поставщикам (D2-2), 06:00 по Ташкенту.

Обратимо: обратная миграция удаляет задачу (расписание остаётся — оно общее)."""

from django.db import migrations

TASK_NAME = "supply.notify_overdue_orders (daily)"


def seed(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="6",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Asia/Tashkent",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={
            "crontab": schedule,
            "task": "supply.notify_overdue_orders",
            "enabled": True,
            "description": "Уведомить о заказах поставщикам, не полученных к ожидаемой дате.",
        },
    )


def unseed(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("supply", "0001_d2_2_stock_and_procurement"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
