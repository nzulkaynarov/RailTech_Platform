from ai.models import AIJob, ImportTask
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import deal_attachment_path, get_private_storage


class AttachmentKind(models.TextChoices):
    """Role of an attachment. SOURCE = the original file the заявка was parsed from
    (the seller cross-checks recognised lines against it); SUPPORTING = any extra
    document the buyer attaches (cover letter, drawing, spec)."""

    SOURCE = "SOURCE", _("Исходник заявки")
    SUPPORTING = "SUPPORTING", _("Документ")


class Attachment(models.Model):
    """
    Универсальный файл-вложение.

    Вместо опасного GenericForeignKey используем явные FK к каждой сущности.
    PostgreSQL гарантирует целостность данных + быстрые JOIN-запросы.
    При удалении родительского объекта файл каскадно удаляется.
    """

    file = models.FileField(
        upload_to=deal_attachment_path,
        storage=get_private_storage,
        verbose_name=_("Файл"),
        help_text=_("Загруженный файл вложения"),
    )
    original_filename = models.CharField(
        max_length=255,
        verbose_name=_("Имя файла"),
        help_text=_("Оригинальное имя загруженного файла"),
    )
    kind = models.CharField(
        max_length=20,
        choices=AttachmentKind.choices,
        default=AttachmentKind.SUPPORTING,
        db_index=True,
        verbose_name=_("Тип вложения"),
        help_text=_("SOURCE = исходный файл заявки (из него распознаны позиции); SUPPORTING = доп. документ"),
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_attachments",
        verbose_name=_("Загрузил"),
        help_text=_("Пользователь, загрузивший файл"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата загрузки"),
    )

    # Явные связи (nullable — файл привязан ровно к одной сущности)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("Товар"),
        help_text=_("Привязка к товару"),
    )
    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("Сделка"),
        help_text=_("Привязка к сделке"),
    )
    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("КП"),
        help_text=_("Привязка к коммерческому предложению"),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("Компания"),
        help_text=_("Привязка к компании"),
    )

    class Meta:
        verbose_name = _("Вложение")
        verbose_name_plural = _("Вложения")
        # MED-7: Ensure exactly one FK is populated
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        product__isnull=False,
                        deal__isnull=True,
                        quote__isnull=True,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=False,
                        quote__isnull=True,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=True,
                        quote__isnull=False,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=True,
                        quote__isnull=True,
                        company__isnull=False,
                    )
                ),
                name="exactly_one_fk_populated",
            )
        ]
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.original_filename


__all__ = [
    "AIJob",
    "Attachment",
    "AttachmentKind",
    "ImportTask",
]
