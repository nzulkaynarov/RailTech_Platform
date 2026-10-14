from django.utils.translation import gettext_lazy as _

from core.models import AbstractLookup


class CompanyType(AbstractLookup):
    """
    Тип/роль компании на платформе.
    Seed: CLIENT, MANUFACTURER, SUPPLIER, LOGISTICS_PROVIDER
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип компании")
        verbose_name_plural = _("Справочник: Типы компаний")
