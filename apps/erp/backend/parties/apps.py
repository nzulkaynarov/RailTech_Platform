from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PartiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parties"
    verbose_name = _("Компании и контакты")
