"""Задание расчёта по резолюции EDS (EDS-01, runbook волны 12 §2.4).

Директор накладывает резолюцию на входящее письмо в EDS; EDS публикует `uz.railtech.eds.letter.resolved.v1`, ERP по
сделке письма заводит задание расчёта: исполнители с зоной ответственности, срок, порог маржи. Резолюция — данные EDS
(владелец полей — EDS), здесь её проекция: одна строка на письмо (`eds_letter_id`), повтор или новая резолюция того же
письма обновляет строку, а не множит её. Исполнитель — `crm_user_id` (идентичность — CRM) и пользователь ERP через
`CrmUserMapping`; несопоставленный сотрудник остаётся строкой без пользователя (и записью в журнале сделки).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class CalcZone(models.TextChoices):
    """Зона ответственности исполнителя резолюции (`Zone` в `packages/contracts/events/eds/_defs.v1.json`)."""

    GOODS = "goods", _("Товары и склад")
    SERVICES = "services", _("Услуги")
    PAYMENT_TERMS = "payment_terms", _("Условия оплаты")


#: Зоны, по которым КП собирает визы расчёта (`CalcZone` событий ERP: снабженец и гл. инженер).
VISA_ZONES = (CalcZone.GOODS, CalcZone.SERVICES)


class CalcTask(models.Model):
    """Задание расчёта по сделке — проекция резолюции EDS на входящее письмо."""

    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="calc_tasks",
        verbose_name=_("Сделка"),
    )
    eds_letter_id = models.UUIDField(
        unique=True,
        verbose_name=_("Письмо EDS"),
        help_text=_("Входящее письмо EDS, на которое наложена резолюция (одно задание на письмо)"),
    )
    letter_number = models.CharField(max_length=32, verbose_name=_("Номер письма"), help_text=_("ВХ-NNN/ГГ"))
    letter_subject = models.CharField(max_length=300, blank=True, default="", verbose_name=_("Тема письма"))
    resolution_text = models.TextField(verbose_name=_("Текст резолюции"))
    due = models.DateField(verbose_name=_("Срок расчёта"))
    min_margin_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Маржа не ниже, %"),
        help_text=_("Порог маржи из резолюции (владелец поля — EDS); пусто — ограничения нет"),
    )
    decided_by_crm_user_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("Директор (CRM)"))
    decided_by_name = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Директор"))
    decided_at = models.DateTimeField(verbose_name=_("Время резолюции"))
    eds_event_id = models.UUIDField(
        null=True,
        blank=True,
        verbose_name=_("Последнее событие EDS"),
        help_text=_("id события letter.resolved, применённого последним: повтор того же события — без изменений"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Задание расчёта")
        verbose_name_plural = _("Задания расчёта")
        ordering = ["-decided_at", "-id"]

    def __str__(self):
        return f"Расчёт по {self.letter_number} (сделка #{self.deal_id})"


class CalcTaskAssignee(models.Model):
    """Исполнитель задания расчёта: сотрудник CRM, зона и пользователь ERP (если сопоставлен)."""

    task = models.ForeignKey(CalcTask, on_delete=models.CASCADE, related_name="assignees", verbose_name=_("Задание"))
    crm_user_id = models.BigIntegerField(verbose_name=_("Сотрудник (CRM)"))
    zone = models.CharField(max_length=16, choices=CalcZone.choices, verbose_name=_("Зона"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calc_assignments",
        verbose_name=_("Пользователь ERP"),
        help_text=_("Пусто — сотрудник CRM ещё не заведён в ERP (нет CrmUserMapping)"),
    )

    class Meta:
        verbose_name = _("Исполнитель расчёта")
        verbose_name_plural = _("Исполнители расчёта")
        ordering = ["task_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "crm_user_id", "zone"], name="calc_assignee_task_user_zone_uniq"),
        ]

    def __str__(self):
        return f"crm_user #{self.crm_user_id} · {self.zone}"
