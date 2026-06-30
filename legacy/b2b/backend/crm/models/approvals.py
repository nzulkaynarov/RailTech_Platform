"""КП internal approval chain — the ordered list of approvers/reviewers/informed
recipients a КП routes through before it can be sent to the client (ADR: unified
approval workflow). The set of rows IS the routing request — no separate header.

World-standard recipient taxonomy (DocuSign / RACI):
  • HEAD     — the mandatory final approver («руководитель»), Accountable, last gate.
  • APPROVER — an intermediate reviewer who acts and BLOCKS, Responsible/Consulted.
  • INFORMED — notified only, never blocks, no decision (CC / RACI Informed).

The list is AUTO-derived from the access matrix (Permission) + КП risk on submit, then
editable with guardrails. Attribution lives here (approver = assigned, acted_by = actual),
so we don't sprinkle per-stage *_by fields on Quote. Tracked by pghistory.
"""

import pghistory
from django.db import models
from django.utils.translation import gettext_lazy as _


class StepParticipation(models.TextChoices):
    HEAD = "HEAD", _("Руководитель")
    APPROVER = "APPROVER", _("Согласовант")
    INFORMED = "INFORMED", _("Для информации")


class StepStatus(models.TextChoices):
    PENDING = "PENDING", _("Ожидает")
    APPROVED = "APPROVED", _("Согласовано")
    REJECTED = "REJECTED", _("Отклонено")
    SKIPPED = "SKIPPED", _("Пропущено")
    RECALLED = "RECALLED", _("Отозвано")


class StepTrigger(models.TextChoices):
    HEAD_FINAL = "HEAD_FINAL", _("Финальное согласование")
    TRADE_REVIEW = "TRADE_REVIEW", _("Проверка ВЭД")
    BELOW_FLOOR_ESCALATION = "BELOW_FLOOR_ESCALATION", _("Эскалация: маржа ниже порога")
    INFORMED = "INFORMED", _("Для информации")
    MANUAL = "MANUAL", _("Добавлен вручную")


@pghistory.track()
class QuoteApprovalStep(models.Model):
    """One node in a КП's approval chain. Same `order` = parallel; lower `order` acts first.
    A HEAD step is always last and mandatory; INFORMED steps have no order gate."""

    quote = models.ForeignKey(
        "crm.Quote", on_delete=models.CASCADE, related_name="approval_steps", verbose_name=_("КП")
    )
    order = models.PositiveSmallIntegerField(
        default=1,
        verbose_name=_("Порядок"),
        help_text=_("Одинаковый порядок = параллельно; меньший = раньше. Руководитель — последним."),
    )
    participation = models.CharField(
        max_length=12, choices=StepParticipation.choices, default=StepParticipation.APPROVER, verbose_name=_("Роль в цепочке")
    )
    # WHO should act: a specific member, and/or any holder of a role (queue model — lets a
    # small team have a stand-in). The act path re-checks the permission regardless.
    approver = models.ForeignKey(
        "accounts.CompanyMember",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_steps",
        verbose_name=_("Назначенный согласовант"),
    )
    approver_role = models.ForeignKey(
        "accounts.CompanyRole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_steps",
        verbose_name=_("Роль-согласовант"),
    )
    acted_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто фактически решил"),
    )
    status = models.CharField(
        max_length=10, choices=StepStatus.choices, default=StepStatus.PENDING, verbose_name=_("Статус шага")
    )
    is_mandatory = models.BooleanField(
        default=False, verbose_name=_("Обязательный"), help_text=_("Нельзя удалить (руководитель).")
    )
    is_auto = models.BooleanField(
        default=True, verbose_name=_("Авто"), help_text=_("Создан правилом (нельзя удалить); False = добавлен вручную.")
    )
    trigger_reason = models.CharField(
        max_length=24, choices=StepTrigger.choices, default=StepTrigger.MANUAL, verbose_name=_("Причина")
    )
    # Snapshot of the condition value at submit (e.g. margin %), for smart re-approval (P2).
    tested_value = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name=_("Снимок значения условия")
    )
    comment = models.TextField(blank=True, verbose_name=_("Комментарий решения"))
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Время решения"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))

    class Meta:
        verbose_name = _("Шаг согласования КП")
        verbose_name_plural = _("Шаги согласования КП")
        ordering = ["quote_id", "order", "id"]

    def __str__(self):
        return f"{self.get_participation_display()} · {self.get_status_display()} (КП #{self.quote_id})"
