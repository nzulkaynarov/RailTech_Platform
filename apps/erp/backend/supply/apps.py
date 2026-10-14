from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SupplyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "supply"
    verbose_name = _("Снабжение")
