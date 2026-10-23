"""B3 (ADR-0014): журнал вебхуков ERP → CRM заменён шиной rt_bus (outbox/delivery в приложении `rt_bus`).

Данных прода нет (карт-бланш владельца) — журнал удаляется без переноса. Вместе с ним снимается задача Beat
`integration-requeue-stuck-webhooks`: DatabaseScheduler хранит её строкой в БД и без этой правки продолжил бы слать
несуществующую задачу `integration.requeue_stuck_webhook_events` каждые 5 минут.
"""

from django.db import migrations

STALE_PERIODIC_TASKS = ["integration-requeue-stuck-webhooks"]


def drop_stale_beat_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name__in=STALE_PERIODIC_TASKS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("integration", "0006_crmusermapping_provision_snapshot"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="IntegrationWebhookEvent"),
        migrations.RunPython(drop_stale_beat_tasks, migrations.RunPython.noop),
    ]
