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
    # L1 (spec-bilingual-ru-en): машинный код события + параметры интерполяции. Текст
    # собирает клиент на языке ЗРИТЕЛЯ — тот же приём, что у ActivityLog (structured
    # timeline). `title`/`message` остаются RU-fallback: для строк, записанных до L1, и
    # для Unfold-админки, которая читает их напрямую.
    event_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Код события"),
        help_text=_("Машинный код для локализуемого текста (deal.created, act.issued, ...)"),
    )
    event_params = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Параметры события"),
        help_text=_("Значения для подстановки в перевод на клиенте"),
    )
    title = models.CharField(
        max_length=255,
        verbose_name=_("Заголовок"),
        help_text=_("Краткий заголовок уведомления (RU-fallback; текст собирается по event_code)"),
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
        help_text=_("Код шаблона, например 'setup_password', 'invite_member'"),
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


class EmailTemplate(models.Model):
    """DB-editable override for the file-based email templates.

    Platform Operators edit transactional email copy from the React admin
    without a code deploy. `notifications.emails.send_templated_email` renders
    from an active row when one exists for the given key, ELSE falls back to the
    file templates in backend/templates/emails/ — so this is purely additive and
    backward compatible: an empty table changes nothing.

    `key` matches the file template name (e.g. 'setup_password',
    'invite_member', 'quote_sent', 'reset_password'). The stored subject/html/text are Django
    templates rendered against the same context the calling service provides;
    `available_variables` documents those merge vars for the editor.
    """

    key = models.SlugField(
        max_length=100,
        db_index=True,
        verbose_name=_("Ключ"),
        help_text=_("Совпадает с именем файлового шаблона: 'setup_password', 'invite_member', 'quote_sent', …"),
    )
    # L2 (spec-bilingual-ru-en): у оверрайда появилось языковое измерение. Пустое значение =
    # «на любом языке» — так ведут себя строки, заведённые до L2: они продолжают
    # перекрывать файловый шаблон для всех получателей. Уникален не ключ, а ПАРА
    # (ключ, язык), иначе английский оверрайд вытеснял бы русский.
    language = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Язык"),
        help_text=_("Код языка (ru, en). Пусто — шаблон применяется для всех языков."),
    )
    subject = models.CharField(
        max_length=255,
        verbose_name=_("Тема"),
        help_text=_("Шаблон темы письма. Поддерживает переменные контекста, напр. {{ company_name }}."),
    )
    html_body = models.TextField(
        blank=True,
        verbose_name=_("Тело (HTML)"),
        help_text=_("HTML-версия письма. Пусто — HTML-альтернатива не прикладывается."),
    )
    text_body = models.TextField(
        verbose_name=_("Текст (plain)"),
        help_text=_("Текстовая версия письма. Рендерится без HTML-экранирования (ссылки не ломаются)."),
    )
    available_variables = models.TextField(
        blank=True,
        verbose_name=_("Доступные переменные"),
        help_text=_("Человекочитаемая справка по merge-переменным, которые передаёт контекст для этого ключа."),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивный шаблон игнорируется — отправка возвращается к файловому шаблону."),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_email_templates",
        verbose_name=_("Кто изменил"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Изменён"),
    )

    class Meta:
        verbose_name = _("Шаблон email")
        verbose_name_plural = _("Шаблоны email")
        ordering = ["key", "language"]
        constraints = [
            models.UniqueConstraint(fields=["key", "language"], name="emailtemplate_key_language_unique"),
        ]

    def __str__(self):
        state = "" if self.is_active else " (выкл.)"
        lang = f" [{self.language}]" if self.language else ""
        return f"{self.key}{lang}{state}"
