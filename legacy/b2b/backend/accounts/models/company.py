from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import company_logo_path, get_public_storage
from master_data.models import Country

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Основные модели
# ────────────────────────────────────────────


class Company(models.Model):
    """
    Юридическое лицо / Организация.
    Одна компания может быть одновременно и поставщиком, и клиентом (через M2M types).
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Название"),
        help_text=_("Полное наименование организации"),
    )
    # INN is deferred from registration (Phase 1) — collected later at KYC.
    # null=True keeps the unique index valid for many INN-less companies
    # (Postgres treats NULLs as distinct); the regex validator still runs once
    # an INN is actually provided.
    inn = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[RegexValidator(settings.INN_VALIDATION_REGEX, _("Некорректный формат ИНН."))],
        verbose_name=_("ИНН"),
        help_text=_("Идентификационный номер налогоплательщика"),
    )
    types = models.ManyToManyField(
        "accounts.CompanyType",
        related_name="companies",
        blank=True,
        verbose_name=_("Роли на платформе"),
        help_text=_("Роли компании: клиент, поставщик, производитель"),
    )
    verification_status = models.ForeignKey(
        "accounts.VerificationStatus",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name=_("Статус верификации"),
        help_text=_("Текущий статус KYC-проверки компании"),
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name=_("Верифицирован"),
        help_text=_("Компания прошла базовую проверку RailTech"),
    )
    has_iso9001 = models.BooleanField(
        default=False,
        verbose_name=_("ISO 9001"),
        help_text=_("Имеется сертификат качества ISO 9001"),
    )
    trust_score = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Индекс доверия"),
        help_text=_("Рейтинг доверия поставщика (0-100)"),
    )
    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
        verbose_name=_("Страна"),
        help_text=_("Страна регистрации юридического лица"),
    )

    # Реквизиты
    legal_address = models.TextField(
        blank=True,
        verbose_name=_("Юридический адрес"),
        help_text=_("Полный юридический адрес организации"),
    )
    bank_account = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Расчётный счёт"),
        help_text=_("Номер расчётного счёта в банке"),
    )
    mfo = models.CharField(
        max_length=10,
        blank=True,
        verbose_name=_("МФО"),
        help_text=_("Межфилиальный оборот (код банка)"),
    )
    contact_person = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Контактное лицо"),
        help_text=_("ФИО ответственного представителя компании"),
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Телефон"),
        help_text=_("Контактный телефон компании"),
    )
    email = models.EmailField(
        blank=True,
        verbose_name=_("Email"),
        help_text=_("Основной email компании для уведомлений"),
    )
    website = models.URLField(
        max_length=255,
        blank=True,
        verbose_name=_("Веб-сайт"),
        help_text=_("Адрес корпоративного сайта"),
    )
    logo = models.ImageField(
        upload_to=company_logo_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Логотип"),
        help_text=_("Логотип компании для отображения на платформе"),
    )
    kyc_notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки по KYC"),
        help_text=_("Внутренние заметки менеджера (не видны клиенту)"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата регистрации"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Компания")
        verbose_name_plural = _("Компании")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.inn})"


class CompanyMember(models.Model):
    """
    Связь «Пользователь ↔ Компания» с ролью.
    Один пользователь может состоять в нескольких компаниях с разными ролями.
    """

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Пользователь"),
        help_text=_("Участник компании"),
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Компания"),
        help_text=_("Организация, в которой состоит пользователь"),
    )
    role = models.ForeignKey(
        "accounts.WorkspaceRole",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Роль в компании"),
        help_text=_("Функциональная роль внутри рабочего пространства"),
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Основная компания"),
        help_text=_("Основное рабочее пространство пользователя"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Деактивированные участники не имеют доступа к компании"),
    )
    # Per-member capabilities. The company's OWNER distributes selling/buying
    # rights inside the team. Defaults are True so existing memberships keep
    # their current access; OWNER can turn flags off explicitly.
    can_sell = models.BooleanField(
        default=True,
        verbose_name=_("Может продавать"),
        help_text=_(
            "Разрешено подавать SupplierBid, управлять каталогом и офферами "
            "от лица компании. Выключается владельцем компании."
        ),
    )
    can_buy = models.BooleanField(
        default=True,
        verbose_name=_("Может покупать"),
        help_text=_(
            "Разрешено создавать заявки/сделки и принимать bid'ы от лица " "компании. Выключается владельцем компании."
        ),
    )
    joined_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата вступления"),
    )

    class Meta:
        verbose_name = _("Участник компании")
        verbose_name_plural = _("Участники компаний")
        unique_together = [("user", "company")]
        ordering = ["-is_primary", "joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_primary=True),
                name="unique_primary_company_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} → {self.company.name} [{self.role}]"
