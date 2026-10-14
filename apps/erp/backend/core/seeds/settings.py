"""System settings seed (singleton pk=1)."""


def seed_system_settings(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    SystemSetting = apps.get_model("core", "SystemSetting")
    SystemSetting.objects.get_or_create(
        pk=1,
        defaults={
            "platform_name": "RailTech B2B Ecosystem",
        },
    )
