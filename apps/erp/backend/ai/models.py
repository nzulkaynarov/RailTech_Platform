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


class AICall(models.Model):
    """Журнал вызовов шлюза LiteLLM — одна строка на вызов модели (M1-ERP-06).

    Источник дневного бюджета ERP (`AI_DAILY_BUDGET_USD`: сумма `cost_usd` за календарный день
    `TIME_ZONE`), версии промпта у ответа и статуса ИИ для консоли администратора (§3.13).
    Стоимость — из заголовка шлюза `x-litellm-response-cost`. Текст промптов и ответов здесь
    НЕ хранится (он — в трейсе Langfuse), только метаданные вызова.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Время вызова"))
    session_id = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("Задача"),
        help_text=_("ID ИИ-задачи (Celery) или импорта; совпадает с session_id трейса Langfuse"),
    )
    user_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("Сотрудник"))
    feature = models.CharField(max_length=32, verbose_name=_("Функция"), help_text=_("Тег feature= вызова"))
    model_alias = models.CharField(max_length=32, verbose_name=_("Алиас модели"))
    prompt_name = models.CharField(max_length=64, verbose_name=_("Промпт"))
    prompt_version = models.CharField(max_length=16, verbose_name=_("Версия промпта (хэш)"))
    status = models.CharField(
        max_length=16,
        verbose_name=_("Исход"),
        help_text=_("ok / refusal / truncated / invalid_json / error / budget"),
    )
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name=_("Код ошибки"))
    input_tokens = models.PositiveIntegerField(default=0, verbose_name=_("Токены на входе"))
    output_tokens = models.PositiveIntegerField(default=0, verbose_name=_("Токены на выходе"))
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0, verbose_name=_("Стоимость, USD"))
    latency_ms = models.PositiveIntegerField(default=0, verbose_name=_("Длительность, мс"))

    class Meta:
        verbose_name = _("Вызов модели")
        verbose_name_plural = _("Вызовы моделей")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.feature}/{self.model_alias}: {self.status}"
