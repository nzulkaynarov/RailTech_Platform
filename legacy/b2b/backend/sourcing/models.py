from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.models import DomainType
from core.storage import deal_attachment_path, get_private_storage


class DomainKeyword(models.Model):
    """MED-2: Dynamic routing keywords for Smart Match."""

    domain_type = models.ForeignKey(
        DomainType,
        on_delete=models.CASCADE,
        related_name="keywords",
        verbose_name=_("Тип домена"),
        help_text=_("Домен каталога, к которому привязано ключевое слово"),
    )
    keyword = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("Ключевое слово"),
        help_text=_("Слово для автоматического определения домена при Excel-импорте (регистронезависимое)"),
    )

    class Meta:
        verbose_name = _("Ключевое слово домена")
        verbose_name_plural = _("Ключевые слова доменов")

    def __str__(self):
        return f"{self.keyword} -> {self.domain_type.name}"


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
    uploaded_by = models.ForeignKey(
        "accounts.CustomUser",
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
        "crm.Deal",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("Сделка"),
        help_text=_("Привязка к сделке"),
    )
    message = models.ForeignKey(
        "crm.Message",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("Сообщение"),
        help_text=_("Привязка к сообщению в чате"),
    )
    quote = models.ForeignKey(
        "crm.Quote",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("КП"),
        help_text=_("Привязка к коммерческому предложению"),
    )
    company = models.ForeignKey(
        "accounts.Company",
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
                        message__isnull=True,
                        quote__isnull=True,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=False,
                        message__isnull=True,
                        quote__isnull=True,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=True,
                        message__isnull=False,
                        quote__isnull=True,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=True,
                        message__isnull=True,
                        quote__isnull=False,
                        company__isnull=True,
                    )
                    | models.Q(
                        product__isnull=True,
                        deal__isnull=True,
                        message__isnull=True,
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


class ImportTask(models.Model):
    """
    Persistent tracking of Celery import tasks.
    Replaces volatile cache-based ownership for IDOR protection.
    """

    TASK_TYPE_CHOICES = [
        ("DEAL_IMPORT", _("Импорт Excel в сделку")),
        ("CATALOG_IMPORT", _("Импорт каталога")),
    ]

    celery_task_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name=_("ID задачи Celery"),
        help_text=_("Уникальный идентификатор асинхронной задачи"),
    )
    owner = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="import_tasks",
        verbose_name=_("Инициатор"),
        help_text=_("Пользователь, запустивший импорт"),
    )
    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_tasks",
        verbose_name=_("Сделка"),
        help_text=_("Сделка, в которую импортируются данные"),
    )
    task_type = models.CharField(
        max_length=20,
        choices=TASK_TYPE_CHOICES,
        verbose_name=_("Тип задачи"),
        help_text=_("Вид импорта: Excel в сделку или каталог"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("Задача импорта")
        verbose_name_plural = _("Задачи импорта")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_type}: {self.celery_task_id}"
