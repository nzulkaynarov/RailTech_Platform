"""Документы товара и техдокументация (D2-3, CAT-CARD-1): ТЗ, чертежи, сертификаты, паспорта, инструкции, регламенты ПНР.

Файл с привязкой к позиции номенклатуры и/или к заявке-проекту. Хранилище — приватный бакет ERP `erp-private`, как
вложения сделок и документы товаров (`ProductDocument`): наружу только потоком через аутентифицированное представление
(`catalog.views.tech_docs`), адрес в хранилище не отдаётся. `ProductDocument` (паспорт изделия в карточке товара) остаётся
как есть — старый фронт его использует (до P6); Платформа работает только с этим реестром: его данные миграцией
`0011_cat_card_data` перенесены сюда. Вид документа — справочник `DocumentKind` (данные, правит администратор), а не список в коде.
"""

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import get_private_storage, tech_document_path

#: Код вида: строчные латинские буквы, цифры, «_» и «-», до 32 знаков. Тот же шаблон держит BFF Платформы
#: (`schemas_erp_catalog.KIND_CODE`): код с заглавными в справочник не попадает.
KIND_CODE_PATTERN = r"^[a-z0-9_-]{1,32}$"


class DocumentKind(models.Model):
    """Вид документа товара — справочник-данные (CAT-CARD-1, эталоны: 1С:УТ «Сертификаты номенклатуры», GS1 GDSN).

    Код стабилен (по нему сравнивает код и хранится `TechDocument.kind`), название и флаги правит администратор. Вид с флагом
    «имеет срок действия» нужен, когда документ подтверждает соответствие: срок — часть его смысла. «Видно клиенту по
    умолчанию» подставляется в новый документ; решает сотрудник на каждом документе."""

    code = models.CharField(
        max_length=32,
        unique=True,
        validators=[
            RegexValidator(
                KIND_CODE_PATTERN,
                message=_("Код — строчные латинские буквы, цифры, «_» и «-», до 32 знаков."),
            )
        ],
        verbose_name=_("Код"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Название"))
    has_validity = models.BooleanField(
        default=False, verbose_name=_("Имеет срок действия"), help_text=_("Сертификат, декларация: срок «действует до»")
    )
    client_visible_default = models.BooleanField(
        default=False,
        verbose_name=_("По умолчанию видно клиенту"),
        help_text=_("Подставляется в новый документ этого вида; сотрудник может изменить"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))
    sort_order = models.PositiveSmallIntegerField(default=100, verbose_name=_("Порядок"))

    class Meta:
        verbose_name = _("Вид документа товара")
        verbose_name_plural = _("Виды документов товара")
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name


#: Виды, подтверждающие соответствие товара (нужны полноте карточки, если категория требует такой документ).
CONFORMITY_KIND_CODES = frozenset({"certificate", "declaration"})


class TechDocument(models.Model):
    #: Вид — код записи `DocumentKind` (мягкая ссылка: коды tz/drawing/certificate/pnr/other существовали до справочника).
    kind = models.CharField(max_length=32, default="other", db_index=True)
    title = models.CharField(max_length=255, verbose_name=_("Название"))
    file = models.FileField(upload_to=tech_document_path, storage=get_private_storage, verbose_name=_("Файл"))
    number = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Номер"))
    issued_by = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Кем выдан"))
    issued_at = models.DateField(null=True, blank=True, verbose_name=_("Выдан"))
    valid_until = models.DateField(
        null=True, blank=True, verbose_name=_("Действует до"), help_text=_("Пусто — бессрочно")
    )
    client_visible = models.BooleanField(default=False, verbose_name=_("Видно клиенту"))
    original_name = models.CharField(max_length=255, verbose_name=_("Имя файла"))
    content_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_documents",
        verbose_name=_("Позиция номенклатуры"),
    )
    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_documents",
        verbose_name=_("Заявка или проект"),
    )
    uploaded_by = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Техническая документация")
        verbose_name_plural = _("Документы: Техдокументация")
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title
