"""Бригады и исполнители услуг (D2-3, SPEC-v3 §7.4 «Справочники»).

Справочник, на который опирается расчёт услуги: гл. инженер выбирает исполнителя, ставка и дни дают закупку
услуги. Бригада — не сотрудник ERP и не контрагент: у неё нет входа и документов, это строка справочника
(SAP «ресурс», Odoo «работник по подряду»). Ставка — закрытое поле: её видит держатель зоны услуг или
`quote.view_cost_margin` (`catalog.services.desk_access`), остальным ERP не отдаёт её вовсе.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import Currency


class Brigade(models.Model):
    class Kind(models.TextChoices):
        BRIGADE = "brigade", _("Бригада")
        PERSON = "person", _("Исполнитель")
        SUBCONTRACTOR = "subcontractor", _("Подрядчик")

    class RateUnit(models.TextChoices):
        DAY = "day", _("за день")
        HOUR = "hour", _("за час")

    name = models.CharField(max_length=255, verbose_name=_("Название"))
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.BRIGADE, verbose_name=_("Вид"))
    specialization = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("Специализация"), help_text=_("Что умеет: монтаж, ПНР…")
    )
    headcount = models.PositiveSmallIntegerField(default=1, verbose_name=_("Человек в составе"))
    rate = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Ставка"),
        help_text=_("Закрытое поле: видит держатель зоны услуг или права на себестоимость."),
    )
    rate_unit = models.CharField(
        max_length=8, choices=RateUnit.choices, default=RateUnit.DAY, verbose_name=_("Единица ставки")
    )
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name=_("Валюта ставки")
    )
    note = models.CharField(max_length=500, blank=True, default="", verbose_name=_("Примечание"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Работает"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Бригада или исполнитель услуг")
        verbose_name_plural = _("Справочник: Бригады и исполнители услуг")
        ordering = ["name", "id"]

    def __str__(self):
        return self.name
