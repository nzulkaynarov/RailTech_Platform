from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import (
    get_private_storage,
    kyc_document_path,
)

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


class KYCDocument(models.Model):
    """Документы для верификации (KYC) компании."""

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="kyc_documents",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относится документ"),
    )
    doc_type = models.ForeignKey(
        "accounts.KYCDocType",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Тип документа"),
        help_text=_("Вид документа из справочника (устав, лицензия, паспорт)"),
    )
    file = models.FileField(
        upload_to=kyc_document_path,
        storage=get_private_storage,
        verbose_name=_("Файл"),
        help_text=_("Загруженный скан документа (хранится в приватном хранилище)"),
    )
    original_filename = models.CharField(
        max_length=255,
        verbose_name=_("Оригинальное имя файла"),
        help_text=_("Имя файла, загруженного пользователем"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата загрузки"),
    )

    class Meta:
        verbose_name = _("KYC-документ")
        verbose_name_plural = _("KYC-документы")

    def __str__(self):
        return f"{self.doc_type} — {self.company.name}"
