"""Запрос на смену банковских реквизитов компании из кабинета (FX-4, решение владельца 2026-11-08).

Реквизиты меняются только после подтверждения сотрудником. Запрос на компанию один активный: частичный уникальный индекс держит
это на уровне базы. В строке — полный новый счёт (его сверяет сотрудник); наружу журнала и уведомлений он не уходит. Логика —
`portal/services/bank_details_change.py`.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class BankDetailsChangeStatus(models.TextChoices):
    PENDING = "pending", _("На проверке")
    APPROVED = "approved", _("Подтверждён")
    REJECTED = "rejected", _("Отклонён")


class BankDetailsChangeRequest(models.Model):
    company = models.ForeignKey(
        "parties.Company", on_delete=models.CASCADE, related_name="bank_change_requests", verbose_name=_("Компания")
    )
    status = models.CharField(
        max_length=10,
        choices=BankDetailsChangeStatus.choices,
        default=BankDetailsChangeStatus.PENDING,
        verbose_name=_("Статус"),
    )
    old_bank_details = models.TextField(blank=True, default="", verbose_name=_("Реквизиты на момент подачи"))
    new_bank_details = models.TextField(blank=True, default="", verbose_name=_("Запрошенные реквизиты"))
    requested_by_contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто подал"),
    )
    requested_by_name = models.CharField(max_length=255, verbose_name=_("Имя подавшего"))
    requested_by_email = models.EmailField(blank=True, default="", verbose_name=_("Email подавшего"))
    requested_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("IP адрес"))
    user_agent = models.TextField(blank=True, default="", verbose_name=_("User Agent"))
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто решил"),
    )
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Когда решено"))
    reject_reason = models.TextField(blank=True, default="", verbose_name=_("Причина отказа"))
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Запрос на смену реквизитов")
        verbose_name_plural = _("Запросы на смену реквизитов")
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(status="pending"),
                name="portal_bank_change_one_pending_uniq",
            ),
        ]

    def __str__(self):
        return f"BankDetailsChangeRequest({self.company_id}, {self.status})"
