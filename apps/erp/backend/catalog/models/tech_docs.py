"""Техдокументация (D2-3, B-019 часть «ERP · Документация»): ТЗ, чертежи, сертификаты, регламенты ПНР.

Файл с привязкой к позиции номенклатуры и/или к заявке-проекту. Хранилище — приватный бакет ERP `erp-private`, как
вложения сделок и документы товаров (`ProductDocument`): наружу только потоком через аутентифицированное представление
(`catalog.views.tech_docs`), адрес в хранилище не отдаётся. `ProductDocument` (паспорт изделия в карточке товара) остаётся
как есть — старый фронт его использует; здесь отдельный реестр с видом документа и привязкой к проекту.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import get_private_storage, tech_document_path


class TechDocument(models.Model):
    class Kind(models.TextChoices):
        TZ = "tz", _("Техническое задание")
        DRAWING = "drawing", _("Чертёж")
        CERTIFICATE = "certificate", _("Сертификат")
        PNR = "pnr", _("Регламент ПНР")
        OTHER = "other", _("Другое")

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER, db_index=True)
    title = models.CharField(max_length=255, verbose_name=_("Название"))
    file = models.FileField(upload_to=tech_document_path, storage=get_private_storage, verbose_name=_("Файл"))
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
