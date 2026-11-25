"""Заявка на партнёрство и договорной шлюз (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD).

Входная воронка кандидатов в партнёры (поставщики, заводы-изготовители, принципалы) без маскировки под
покупателей на входе. Источники заявки:
1. `public` — внешняя анкета со страницы входа («Стать партнёром / Поставщикам»);
2. `client_cabinet` — запрос действующего клиента на добавление роли партнёра к существующей компании.

Статусы заявки:
- `submitted` — подана, ожидает рассмотрения отделом снабжения;
- `contract_sent` — проект партнёрского договора направлен кандидату;
- `approved` — договор подписан, отношение `partner` активировано;
- `rejected` — заявка отклонена с указанием причины.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import get_private_storage, partner_application_contract_path, partner_application_scan_path

from .relationships import PartnerKind


class PartnerApplicationSource(models.TextChoices):
    PUBLIC = "public", _("Внешний вход")
    CLIENT_CABINET = "client_cabinet", _("Кабинет клиента")
    LETTER = "letter", _("Входящее письмо")
    LEAD = "lead", _("Лид CRM")


class PartnerContractSource(models.TextChoices):
    """ПД-1: откуда договор кандидата. Пусто — договор ещё не подготовлен."""

    TEMPLATE = "template", _("Утверждённый шаблон")
    UPLOAD = "upload", _("Свой файл")


class PartnerContractApproval(models.TextChoices):
    """ПД-1: внутреннее согласование договора. Пусто — согласования не требуется (шаблон без отступлений)."""

    REQUESTED = "requested", _("Ждёт решения держателя «Право»")
    APPROVED = "approved", _("Согласован")
    RETURNED = "returned", _("Возвращён на доработку")


class PartnerApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", _("Подана")
    CONTRACT_SENT = "contract_sent", _("Договор отправлен")
    CANDIDATE_AGREED = "candidate_agreed", _("Согласован кандидатом")
    APPROVED = "approved", _("Одобрена")
    REJECTED = "rejected", _("Отклонена")


class PartnerApplication(models.Model):
    source = models.CharField(
        max_length=20,
        choices=PartnerApplicationSource.choices,
        default=PartnerApplicationSource.PUBLIC,
        verbose_name=_("Источник заявки"),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_applications",
        verbose_name=_("Компания"),
        help_text=_("Заполнено для заявок из кабинета клиента или после привязки/создания компании"),
    )
    applicant_contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Контакт-заявитель"),
        help_text=_("Контакт клиента, подавший заявку из кабинета"),
    )
    applicant_contact_created = models.BooleanField(
        default=False,
        verbose_name=_("Контакт заведён заявкой"),
        help_text=_(
            "Контакт-заявитель создан этой заявкой: при её отклонении он снимается, если ни с чем больше не связан"
        ),
    )
    status = models.CharField(
        max_length=20,
        choices=PartnerApplicationStatus.choices,
        default=PartnerApplicationStatus.SUBMITTED,
        verbose_name=_("Статус"),
    )
    kind = models.CharField(
        max_length=20,
        choices=PartnerKind.choices,
        default=PartnerKind.SUPPLIER,
        verbose_name=_("Вид партнёра"),
    )
    categories_description = models.TextField(
        max_length=2000,
        verbose_name=_("Категории и продукция"),
        help_text=_("Описание категорий продукции, брендов и номенклатуры"),
    )
    company_name = models.CharField(
        max_length=255,
        verbose_name=_("Наименование организации"),
    )
    country = models.ForeignKey(
        "core.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Страна регистрации"),
        help_text=_("Страна регистрации кандидата (справочник ISO 3166-1)"),
    )
    inn = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("ИНН"),
        help_text=_("ИНН для резидентов Узбекистана"),
    )
    registration_number = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Рег. номер (нерезидент)"),
        help_text=_("Регистрационный номер / Tax ID для нерезидентов"),
    )
    contact_name = models.CharField(
        max_length=255,
        verbose_name=_("Контактное лицо"),
    )
    email = models.EmailField(
        verbose_name=_("E-mail"),
    )
    phone = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("Телефон"),
    )
    language = models.CharField(
        max_length=8,
        default="ru",
        verbose_name=_("Язык взаимодействия"),
    )
    consent = models.BooleanField(
        default=True,
        verbose_name=_("Согласие на обработку ПДн"),
    )
    source_ref = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("Номер входящего письма или лида"),
        help_text=_(
            "План 1.9: заявку завёл сотрудник по входящему письму — «Передать в работу»; "
            "ЛП-1: номер лида CRM, если заявка из его карточки"
        ),
    )
    contract_number = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Номер договора"),
    )
    contract_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Дата договора"),
    )
    contract_pdf = models.FileField(
        upload_to=partner_application_contract_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("PDF договора"),
        help_text=_("Файл проекта или согласованного/подписанного договора"),
    )
    # ПД-1: подготовка договора — из утверждённого шаблона библиотеки либо своим файлом; факты, из которых
    # карточка выводит «что дальше» (шаблона и файла нет — отправлять нечего, встроенного образца нет).
    contract_source = models.CharField(
        max_length=16,
        choices=PartnerContractSource.choices,
        blank=True,
        default="",
        verbose_name=_("Откуда договор"),
    )
    contract_template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Шаблон договора"),
        help_text=_("Утверждённая редакция шаблона, по которой собран договор; не меняется при выходе новой"),
    )
    contract_language = models.CharField(
        max_length=8, blank=True, default="", verbose_name=_("Язык договора"), help_text=_("ru, en или uz")
    )
    contract_file = models.FileField(
        upload_to=partner_application_contract_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Файл договора"),
        help_text=_("Договор, который кандидат видит и скачивает: PDF по шаблону или свой файл (PDF, DOCX)"),
    )
    contract_deviation_text = models.TextField(
        max_length=4000,
        blank=True,
        default="",
        verbose_name=_("Отступление от шаблона"),
        help_text=_("Чем текст отличается от утверждённого шаблона; пусто — отступлений нет"),
    )
    contract_approval = models.CharField(
        max_length=16, choices=PartnerContractApproval.choices, blank=True, default="", verbose_name=_("Согласование")
    )
    contract_approval_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    contract_approval_requested_at = models.DateTimeField(null=True, blank=True)
    contract_approval_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    contract_approval_decided_at = models.DateTimeField(null=True, blank=True)
    contract_approval_note = models.TextField(max_length=1000, blank=True, default="")
    candidate_returned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Когда кандидат вернул договор с замечанием"),
        help_text=_("Сбрасывается при повторной отправке; замечание — в `candidate_notes`"),
    )
    signed_scan = models.FileField(
        upload_to=partner_application_scan_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Скан подписанного договора"),
    )
    signed_scan_at = models.DateTimeField(null=True, blank=True)
    contract_draft_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Когда отправлен проект договора"),
    )
    candidate_agreed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Когда согласован кандидатом"),
    )
    candidate_notes = models.TextField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name=_("Комментарий кандидата"),
    )
    rejected_reason = models.TextField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name=_("Причина отклонения"),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто рассмотрел"),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Когда рассмотрено"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создана"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлена"))

    class Meta:
        verbose_name = _("Заявка на партнёрство")
        verbose_name_plural = _("Заявки на партнёрство")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="part_app_status_created_idx"),
            models.Index(fields=["email"], name="part_app_email_idx"),
            models.Index(fields=["inn"], name="part_app_inn_idx"),
        ]

    def __str__(self):
        return f"{self.company_name} ({self.get_kind_display()}): {self.status}"
