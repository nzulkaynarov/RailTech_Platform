from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import (
    company_application_contract_path,
    company_application_nda_path,
    company_application_partnership_path,
    get_private_storage,
)

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Онбординг и подписки
# ────────────────────────────────────────────


class CompanyRoleApplication(models.Model):
    """
    Заявка компании на получение роли (SUPPLIER или MANUFACTURER).
    CLIENT роль назначается автоматически при регистрации.
    """

    STATUS_CHOICES = [
        ("PENDING", _("На рассмотрении")),
        ("DOCUMENTS_REQUIRED", _("Требуются документы")),
        ("PAYMENT_REQUIRED", _("Ожидание оплаты")),
        ("APPROVED", _("Одобрено")),
        ("REJECTED", _("Отклонено")),
    ]

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="role_applications",
        verbose_name=_("Компания"),
        help_text=_("Организация, подавшая заявку"),
    )
    requested_type = models.ForeignKey(
        "accounts.CompanyType",
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name=_("Запрашиваемая роль"),
        help_text=_("Роль, на которую подаётся заявка (SUPPLIER или MANUFACTURER)"),
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default="PENDING",
        verbose_name=_("Статус"),
        help_text=_("Текущий статус рассмотрения заявки"),
    )
    submitted_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_applications",
        verbose_name=_("Подал заявку"),
        help_text=_("Пользователь, инициировавший заявку"),
    )

    # Documents
    contract_file = models.FileField(
        upload_to=company_application_contract_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Договор"),
        help_text=_("Подписанный договор (обязательно для SUPPLIER)"),
    )
    nda_file = models.FileField(
        upload_to=company_application_nda_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("NDA"),
        help_text=_("Соглашение о неразглашении (обязательно для SUPPLIER)"),
    )
    partnership_agreement = models.FileField(
        upload_to=company_application_partnership_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Договор о партнёрстве"),
        help_text=_("Партнёрское соглашение (обязательно для MANUFACTURER)"),
    )

    # Admin review
    reviewed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_applications",
        verbose_name=_("Рассмотрел"),
        help_text=_("Администратор, рассмотревший заявку"),
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name=_("Комментарий"),
        help_text=_("Внутренний комментарий администратора"),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата рассмотрения"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата подачи"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Заявка на роль компании")
        verbose_name_plural = _("Заявки на роли компаний")
        ordering = ["-created_at"]
        unique_together = [("company", "requested_type")]

    def __str__(self):
        return f"{self.company.name} → {self.requested_type.name} ({self.get_status_display()})"
