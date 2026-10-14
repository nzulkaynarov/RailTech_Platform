"""System settings seed (singleton pk=1)."""

import os


def seed_system_settings(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    SystemSetting = apps.get_model("core", "SystemSetting")
    SystemSetting.objects.get_or_create(
        pk=1,
        defaults={
            "platform_name": os.environ.get("PLATFORM_NAME", "ERP"),
            "support_email": os.environ.get("SUPPORT_EMAIL", "support@example.com"),
            "logo_url": "",
            "domain": os.environ.get("PLATFORM_DOMAIN", "erp.localhost"),
        },
    )
