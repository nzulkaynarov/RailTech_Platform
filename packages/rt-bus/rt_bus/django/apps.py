from __future__ import annotations

from django.apps import AppConfig


class RtBusConfig(AppConfig):
    name = "rt_bus.django"
    label = "rt_bus"
    verbose_name = "rt_bus"
    default_auto_field = "django.db.models.BigAutoField"
