from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PartiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parties"
    verbose_name = _("Компании и контакты")

    def ready(self) -> None:
        # СУЩ-2.7: реквизиты компании-контрагента — снимком в CRM при каждом их изменении
        from parties.company_events import connect

        connect()

        # Х-8: у компании с отметкой «Не работать» новые КП, договор, заказ и заявка отказываются
        from parties.do_not_work import connect as connect_do_not_work

        connect_do_not_work()
