"""Notification types seed."""

NOTIFICATION_TYPES = [
    ("INFO", "Информация", 10),
    ("SUCCESS", "Успех", 20),
    ("WARNING", "Предупреждение", 30),
    ("ERROR", "Ошибка", 40),
    ("SYSTEM", "Системное", 50),
]


def seed_notification_types(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        NotificationType = apps.get_model("core", "NotificationType")
    except LookupError:
        NotificationType = apps.get_model("notifications", "NotificationType")

    for code, name, sort_order in NOTIFICATION_TYPES:
        NotificationType.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
