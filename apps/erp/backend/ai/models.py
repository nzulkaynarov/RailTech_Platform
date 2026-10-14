from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


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
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="import_tasks",
        verbose_name=_("Инициатор"),
        help_text=_("Пользователь, запустивший импорт"),
    )
    deal = models.ForeignKey(
        "sales.Deal",
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


class AIJob(models.Model):
    """Ownership record for off-thread AI jobs (ARCH-01).

    The interactive AI endpoints enqueue their LLM call to Celery and return a task_id;
    this row mirrors ImportTask — a persistent IDOR guard so the status endpoint can
    verify the polling user actually owns the task (never a volatile cache).
    """

    celery_task_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name=_("ID задачи Celery"),
        help_text=_("Уникальный идентификатор асинхронной AI-задачи"),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_jobs",
        verbose_name=_("Инициатор"),
        help_text=_("Пользователь, запустивший AI-задачу"),
    )
    feature = models.CharField(
        max_length=32,
        verbose_name=_("AI-функция"),
        help_text=_("Код AI-функции (match, preflight, extract, compose, enrich, quote_diff, draft_quote)"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("AI-задача")
        verbose_name_plural = _("AI-задачи")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.feature}: {self.celery_task_id}"
