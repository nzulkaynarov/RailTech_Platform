from django.db import models
from django.conf import settings
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

    AUDIENCE_USER = 'USER'
    AUDIENCE_PLATFORM_ADMIN = 'PLATFORM_ADMIN'
    AUDIENCE_CHOICES = [
        (AUDIENCE_USER, _('Пользователь')),
        (AUDIENCE_PLATFORM_ADMIN, _('Platform Admin')),
    ]

    audience = models.CharField(
        max_length=20, choices=AUDIENCE_CHOICES, default=AUDIENCE_USER,
        db_index=True,
        verbose_name=_("Аудитория"),
        help_text=_(
            "USER — персональное или broadcast для обычных пользователей. "
            "PLATFORM_ADMIN — операционные алёрты платформы (видит только admin)."
        ),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='notifications', null=True, blank=True,
        verbose_name=_("Получатель"),
        help_text=_("Пользователь-получатель. Пусто = broadcast для всей аудитории."),
    )
    type = models.ForeignKey(
        NotificationType, on_delete=models.PROTECT, related_name='notifications',
        null=True, blank=True,
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
        max_length=500, blank=True,
        verbose_name=_("Ссылка"),
        help_text=_("URL для перехода при клике на уведомление"),
    )
    deal = models.ForeignKey(
        'crm.Deal', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications',
        verbose_name=_("Сделка"),
        help_text=_("Связанная сделка (опционально)"),
    )
    is_read = models.BooleanField(
        default=False, db_index=True,
        verbose_name=_("Прочитано"),
        help_text=_("Пользователь прочитал уведомление"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("Уведомление")
        verbose_name_plural = _("Уведомления")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.type}: {self.title}"
