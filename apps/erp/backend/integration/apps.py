from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integration"
    verbose_name = _("Интеграции")

    def ready(self):
        # Обработчики входящих событий шины rt_bus (проекции данных клиента CRM) — в реестр по умолчанию.
        from . import bus_handlers  # noqa: F401
