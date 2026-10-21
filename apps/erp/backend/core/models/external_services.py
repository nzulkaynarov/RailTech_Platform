from django.db import models
from django.utils.translation import gettext_lazy as _


class ExternalServiceSwitch(models.Model):
    """Выключатель внешнего сервиса ERP, поставленный из центра внешних сервисов CRM (M3-ERP-06).

    Строка есть у сервиса, которого касались выключателем; нет строки — сервис включён. Источник
    истины для `core.external_status.is_enabled`; Redis держит лишь копию на несколько минут.
    """

    code = models.CharField(max_length=32, primary_key=True, verbose_name=_("Код сервиса"))
    enabled = models.BooleanField(default=True, verbose_name=_("Включён"))
    reason = models.CharField(max_length=200, blank=True, default="", verbose_name=_("Причина выключения"))
    changed_at = models.DateTimeField(auto_now=True, verbose_name=_("Изменено"))

    class Meta:
        verbose_name = _("Выключатель внешнего сервиса")
        verbose_name_plural = _("Выключатели внешних сервисов")

    def __str__(self):
        return f"{self.code}: {'on' if self.enabled else 'off'}"
