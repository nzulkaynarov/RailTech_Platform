"""Periodic beat tasks seed (django_celery_beat)."""


def seed_beat_tasks(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return

    # 1. CBU FX refresh: 09:30 daily
    fx_sched, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="9", day_of_week="*", day_of_month="*", month_of_year="*"
    )
    PeriodicTask.objects.get_or_create(
        name="Refresh CBU exchange rates",
        defaults={
            "crontab": fx_sched,
            "task": "master_data.tasks.refresh_exchange_rates",
            "enabled": True,
            "description": "Ежедневный импорт курсов валют с ЦБ РУз (cbu.uz).",
        },
    )

    # 2. TN VED classifier sync: Monday 03:00 weekly
    tnved_sched, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="1", day_of_month="*", month_of_year="*"
    )
    PeriodicTask.objects.get_or_create(
        name="Sync TN VED classifier",
        defaults={
            "crontab": tnved_sched,
            "task": "master_data.tasks.refresh_tnved_codes",
            "enabled": True,
            "description": "Еженедельная синхронизация справочника ТН ВЭД с tarif.customs.uz (ГТК РУз).",
        },
    )

    # 3. Quote expiry check: 05:00 UTC daily
    quote_expiry_sched, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="5",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.update_or_create(
        name="crm.expire_stale_quotes (daily)",
        defaults={
            "crontab": quote_expiry_sched,
            "task": "crm.expire_stale_quotes",
            "enabled": True,
            "description": "Move SENT quotes past valid_until to EXPIRED and notify managers",
        },
    )

    # 4. Overdue delivery check: 04:00 UTC daily
    delivery_sched, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="4",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.update_or_create(
        name="crm.check_overdue_deliveries (daily)",
        defaults={
            "crontab": delivery_sched,
            "task": "crm.check_overdue_deliveries",
            "enabled": True,
            "description": "Warn managers about fulfillments past expected_delivery_date",
        },
    )
