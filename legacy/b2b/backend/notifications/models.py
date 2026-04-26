from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import AbstractLookup


class NotificationType(AbstractLookup):
    """
    Типы уведомлений.
    Seed: INFO, SUCCESS, WARNING, ERROR, SYSTEM
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип уведомления")
        verbose_name_plural = _("Справочник: Типы уведомлений")


class Notification(models.Model):
    """Системные уведомления."""

    AUDIENCE_USER = "USER"
    AUDIENCE_PLATFORM_ADMIN = "PLATFORM_ADMIN"
    AUDIENCE_CHOICES = [
        (AUDIENCE_USER, _("Пользователь")),
        (AUDIENCE_PLATFORM_ADMIN, _("Platform Admin")),
    ]

    audience = models.CharField(
        max_length=20,
        choices=AUDIENCE_CHOICES,
        default=AUDIENCE_USER,
        db_index=True,
        verbose_name=_("Аудитория"),
        help_text=_(
            "USER — персональное или broadcast для обычных пользователей. "
            "PLATFORM_ADMIN — операционные алёрты платформы (видит только admin)."
        ),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name=_("Получатель"),
        help_text=_("Пользователь-получатель. Пусто = broadcast для всей аудитории."),
    )
    type = models.ForeignKey(
        NotificationType,
        on_delete=models.PROTECT,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name=_("Тип"),
        help_text=_("Тип уведомления из справочника"),
    )
    title = models.CharField(
        max_length=255,
        verbose_name=_("Заголовок"),
        help_text=_("Краткий заголовок уведомления"),
    )
    message = models.TextField(
        verbose_name=_("Текст"),
        help_text=_("Полный текст уведомления"),
    )
    link = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Ссылка"),
        help_text=_("URL для перехода при клике на уведомление"),
    )
    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name=_("Сделка"),
        help_text=_("Связанная сделка (опционально)"),
    )
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Прочитано"),
        help_text=_("Пользователь прочитал уведомление"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("Уведомление")
        verbose_name_plural = _("Уведомления")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "audience"], name="notif_user_read_aud_idx"),
        ]

    def __str__(self):
        return f"{self.type}: {self.title}"


class EmailLog(models.Model):
    """Audit log of every email the platform attempts to send.

    Populated by notifications.emails.send_templated_email. Viewable in Unfold
    admin — answers "what was sent to this user and when". Stores both plain
    and HTML bodies for inspection; failed sends are recorded with error text.
    """

    STATUS_SENT = "SENT"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_SENT, _("Отправлено")),
        (STATUS_FAILED, _("Ошибка")),
    ]

    template = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name=_("Шаблон"),
        help_text=_("Код шаблона, например 'setup_password', 'kyc_verified'"),
    )
    channel = models.CharField(
        max_length=40,
        db_index=True,
        default="transactional",
        verbose_name=_("Канал"),
        help_text=_("Ключ из settings.EMAIL_CHANNELS: transactional / marketing / system"),
    )
    subject = models.CharField(
        max_length=255,
        verbose_name=_("Тема"),
    )
    from_email = models.CharField(
        max_length=255,
        verbose_name=_("Отправитель"),
    )
    to_emails = models.JSONField(
        default=list,
        verbose_name=_("Получатели"),
        help_text=_("Список email-адресов"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_logs",
        verbose_name=_("Пользователь"),
        help_text=_("Основной адресат, если известен (для поиска по user__email)"),
    )
    body_text = models.TextField(
        blank=True,
        verbose_name=_("Текст (plain)"),
    )
    body_html = models.TextField(
        blank=True,
        verbose_name=_("Тело (HTML)"),
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_SENT,
        db_index=True,
        verbose_name=_("Статус"),
    )
    error = models.TextField(
        blank=True,
        verbose_name=_("Ошибка"),
        help_text=_("Текст исключения, если отправка не удалась"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Время"),
    )

    class Meta:
        verbose_name = _("Журнал email")
        verbose_name_plural = _("Журнал email-рассылок")
        ordering = ["-created_at"]

    def __str__(self):
        recipients = ", ".join(self.to_emails) if self.to_emails else "—"
        return f"[{self.status}] {self.template} → {recipients}"
