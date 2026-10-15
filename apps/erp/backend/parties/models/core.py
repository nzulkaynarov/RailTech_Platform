"""Company + QuerySet + предикат «кто такой продавец»."""

import pghistory
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.constants import SELLER_COMPANY_TYPES
from core.models import Country
from core.storage import company_logo_path, get_public_storage


def seller_company_q(prefix: str = "") -> models.Q:
    """Предикат «это компания-продавец» для фильтра по СВЯЗИ.

    `prefix` — путь до Company от фильтруемой модели: `seller_company_q("company")` для
    CompanyMember, `seller_company_q("owner_company")` для Product. Без префикса — фильтр по
    самой Company (но там обычно уместнее `Company.objects.sellers()`).
    """
    field = f"{prefix}__types__code__in" if prefix else "types__code__in"
    return models.Q(**{field: SELLER_COMPANY_TYPES})


def active_company_q(prefix: str = "") -> models.Q:
    """«Компания в обороте» — не архивирована.

    Отдельный предикат, потому что архив обязан снимать компанию с ВСЕХ рабочих поверхностей
    сразу. Вкручивать `is_active=True` по местам вызова нельзя: ровно так родился инцидент
    #436, когда два места кодировали одно понятие и разошлись.
    """
    field = f"{prefix}__is_active" if prefix else "is_active"
    return models.Q(**{field: True})


class CompanyQuerySet(models.QuerySet):
    """Публичный словарь выборок по компаниям — импортируется другими приложениями."""

    def sellers(self):
        """Компании, работающие на стороне продавца.

        `.distinct()` обязателен: `types` — M2M, и фильтр по нему размножает строки, если у
        компании несколько подходящих типов.

        Архивные сюда НЕ попадают: подбор продавцов — рабочая поверхность.
        """
        return self.filter(seller_company_q() & active_company_q()).distinct()

    def active(self):
        """Компании в обороте (Odoo: список по умолчанию скрывает архив)."""
        return self.filter(active_company_q())

    def archived(self):
        """Архивные — их видно по явному фильтру, как «Archived» в Odoo."""
        return self.filter(is_active=False)


@pghistory.track()  # G6: audit engineer (Unfold superuser) edits — types, requisites
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
    # INN may be unknown when the back office first records a counterparty.
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
    # INN as STATED for an offline client recorded from the client book — NOT unique (the
    # client-book search-before-create dedups by it). The canonical, unique `inn` above is
    # filled on the company card.
    stated_inn = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        verbose_name=_("ИНН (со слов, до проверки)"),
        help_text=_("ИНН клиента, указанный при заведении в клиентской базе"),
    )
    types = models.ManyToManyField(
        "parties.CompanyType",
        related_name="companies",
        blank=True,
        verbose_name=_("Роли на платформе"),
        help_text=_("Роли компании: клиент, поставщик, производитель"),
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
    bank_details = models.TextField(
        blank=True,
        verbose_name=_("Банковские реквизиты"),
        help_text=_("Полные банковские реквизиты клиента (для портала и документов)"),
    )
    language = models.CharField(
        max_length=10,
        default="ru",
        choices=[("ru", "RU"), ("uz", "UZ"), ("en", "EN")],
        verbose_name=_("Язык документов"),
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
    # False = an "offline" client a seller created in their CRM (no platform login yet).
    # Flips to True when a real user joins the company (signal / invite-accept). Lets the
    # UI and queries distinguish a rep-created account from a self-registered one.
    is_registered = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Зарегистрирована на платформе"),
        help_text=_("False — клиент заведён продавцом вручную (без входа в систему)"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата регистрации"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    # ── Архив (паттерн Odoo Archive) ────────────────────────────────────────────────────
    # Компанию с историей удалить нельзя ни в одном эталоне; из оборота её выводит архив.
    # Флаг живёт РЯДОМ с предикатами выборок выше, а не по местам вызова: иначе повторился
    # бы инцидент #436 — компания не видна покупателю, снять её он не может, а в
    # маршрутизацию она уходит.
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("В обороте"),
        help_text=_("False — компания архивирована: скрыта из подбора и справочников, история сохранена"),
    )
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Архивирована"))
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_companies",
        verbose_name=_("Кто архивировал"),
    )
    archived_reason = models.TextField(blank=True, default="", verbose_name=_("Причина архивации"))

    objects = models.Manager.from_queryset(CompanyQuerySet)()

    class Meta:
        verbose_name = _("Компания")
        verbose_name_plural = _("Компании")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.inn})"

    @property
    def document_profile(self):
        """Get-or-create the company's branded document profile (КП / договор requisites).

        Lazily materialised so every company has a profile object to render from; the
        seller fills it in once via the OWNER endpoint. Cheap OneToOne reverse lookup.
        """
        from .document_profile import CompanyDocumentProfile

        profile = CompanyDocumentProfile.objects.filter(company=self).first()
        if profile is None:
            profile = CompanyDocumentProfile.objects.create(company=self)
        return profile

    @property
    def settings(self):
        """Get-or-create the company's КП-defaults + numbering settings row.

        Lazily materialised so every company has a settings object to read from; the
        seller fills it in via the OWNER endpoint. Cheap OneToOne reverse lookup.
        """
        from .company_settings import CompanySettings

        row = CompanySettings.objects.filter(company=self).first()
        if row is None:
            row = CompanySettings.objects.create(company=self)
        return row

    @property
    def formatted_bank_details(self) -> str:
        """Formatted bank details for portal and documents."""
        if self.bank_details:
            return self.bank_details
        parts = []
        if self.bank_account:
            parts.append(f"р/с {self.bank_account}")
        if self.mfo:
            parts.append(f"МФО {self.mfo}")
        return ", ".join(parts)
