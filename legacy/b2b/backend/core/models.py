"""
Core models — platform-level singletons and configuration.

SystemSetting: single-row table holding global business parameters
(VAT, margins, platform name, feature flags). Edited via React Admin,
inspected via Unfold. Tracked by pghistory for audit trail.
"""
from decimal import Decimal

import pghistory
import pgtrigger
from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _

SYSTEM_SETTING_CACHE_KEY = 'core:system_setting'
SYSTEM_SETTING_CACHE_TTL = 300  # 5 minutes


@pghistory.track(
    pghistory.RowEvent('system_setting.snapshot', row=pghistory.New, operation=pgtrigger.Update),
)
class SystemSetting(models.Model):
    """
    Singleton table for platform-wide business parameters.

    There should be exactly ONE row. Use `SystemSetting.load()` to get it
    (creates a default row if none exists). Never create rows manually.
    """

    # ─── Finance ────────────────────────────────────────────────────────
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('12.00'),
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Процент НДС, применяемый к котировкам"),
    )
    standard_margin = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('15.00'),
        verbose_name=_("Стандартная маржа (%)"),
        help_text=_("Маржа по умолчанию для новых позиций КП"),
    )
    exchange_rate_usd_uzs = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('12500.00'),
        verbose_name=_("Курс USD/UZS"),
        help_text=_("Справочный курс (может обновляться автоматически)"),
    )

    # ─── Platform ───────────────────────────────────────────────────────
    platform_name = models.CharField(
        max_length=200, default='RailTech B2B Ecosystem',
        verbose_name=_("Название платформы"),
    )
    maintenance_mode = models.BooleanField(
        default=False,
        verbose_name=_("Режим обслуживания"),
        help_text=_("Когда включён — пользователи видят заглушку"),
    )

    # ─── Security ───────────────────────────────────────────────────────
    is_two_factor_required = models.BooleanField(
        default=False,
        verbose_name=_("Обязательная 2FA"),
        help_text=_("Требовать двухфакторную аутентификацию для всех пользователей"),
    )

    # ─── Meta ───────────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлено"))

    class Meta:
        verbose_name = _("Системные настройки")
        verbose_name_plural = _("Системные настройки")

    def __str__(self):
        return f"SystemSetting (VAT={self.vat_rate}%, margin={self.standard_margin}%)"

    def save(self, *args, **kwargs):
        # Enforce singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SYSTEM_SETTING_CACHE_KEY)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton
        pass

    @classmethod
    def load(cls) -> 'SystemSetting':
        """
        Load the singleton SystemSetting. Creates a default row if none exists.
        Cached for SYSTEM_SETTING_CACHE_TTL seconds.
        """
        obj = cache.get(SYSTEM_SETTING_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SYSTEM_SETTING_CACHE_KEY, obj, SYSTEM_SETTING_CACHE_TTL)
        return obj


class SupportTicket(models.Model):
    """
    Тикет поддержки: клиент (любой CustomUser) пишет Platform Admin.

    Не связан с Deal/Quote/Lead — это канал прямой связи с платформой.
    """

    STATUS_OPEN = 'OPEN'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_CLOSED = 'CLOSED'
    STATUS_CHOICES = [
        (STATUS_OPEN, _('Открыт')),
        (STATUS_IN_PROGRESS, _('В работе')),
        (STATUS_RESOLVED, _('Решён')),
        (STATUS_CLOSED, _('Закрыт')),
    ]

    PRIORITY_LOW = 'LOW'
    PRIORITY_NORMAL = 'NORMAL'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_URGENT = 'URGENT'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, _('Низкий')),
        (PRIORITY_NORMAL, _('Обычный')),
        (PRIORITY_HIGH, _('Высокий')),
        (PRIORITY_URGENT, _('Срочный')),
    ]

    CATEGORY_BUG = 'BUG'
    CATEGORY_QUESTION = 'QUESTION'
    CATEGORY_BILLING = 'BILLING'
    CATEGORY_FEATURE = 'FEATURE'
    CATEGORY_OTHER = 'OTHER'
    CATEGORY_CHOICES = [
        (CATEGORY_BUG, _('Ошибка в системе')),
        (CATEGORY_QUESTION, _('Вопрос')),
        (CATEGORY_BILLING, _('Оплата/биллинг')),
        (CATEGORY_FEATURE, _('Пожелание')),
        (CATEGORY_OTHER, _('Другое')),
    ]

    subject = models.CharField(
        max_length=255, verbose_name=_("Тема"),
    )
    description = models.TextField(
        verbose_name=_("Описание"),
        help_text=_("Подробное описание обращения"),
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_QUESTION,
        db_index=True, verbose_name=_("Категория"),
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL,
        db_index=True, verbose_name=_("Приоритет"),
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_OPEN,
        db_index=True, verbose_name=_("Статус"),
    )

    created_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_tickets',
        verbose_name=_("Автор"),
    )
    company = models.ForeignKey(
        'accounts.Company', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_tickets',
        verbose_name=_("Компания"),
        help_text=_("Компания автора (берётся из primary_company при создании)"),
    )
    assigned_to = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_tickets',
        verbose_name=_("Назначен"),
        help_text=_("Platform Admin, ведущий тикет"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Решён"))

    class Meta:
        verbose_name = _("Тикет поддержки")
        verbose_name_plural = _("Тикеты поддержки")
        ordering = ['-created_at']

    def __str__(self):
        return f"#{self.pk} {self.subject} ({self.status})"


class SupportTicketMessage(models.Model):
    """Сообщение в переписке по тикету."""

    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name='messages',
        verbose_name=_("Тикет"),
    )
    author = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='support_messages',
        verbose_name=_("Автор"),
    )
    text = models.TextField(verbose_name=_("Текст"))
    is_internal = models.BooleanField(
        default=False,
        verbose_name=_("Внутренняя заметка"),
        help_text=_("Видно только Platform Admin (комментарий для себя или команды)"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Создано"))

    class Meta:
        verbose_name = _("Сообщение тикета")
        verbose_name_plural = _("Сообщения тикетов")
        ordering = ['created_at']

    def __str__(self):
        return f"msg#{self.pk} on ticket #{self.ticket_id}"
