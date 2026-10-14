from decimal import Decimal

import pghistory
import pgtrigger
from django.conf import settings
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from .lookups import DealStage


@pghistory.track(
    pghistory.RowEvent("deal.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("deal.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Deal(models.Model):
    """
    Сделка — процесс переговоров с клиентом.
    Может содержать несколько версий КП (Quote).
    """

    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="deals",
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Компания"),
        help_text=_("Компания-клиент, с которой ведётся сделка. Пусто — черновик-калькулятор без клиента."),
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deals_as_client",
        verbose_name=_("Контактное лицо"),
        help_text=_("Представитель клиента в данной сделке"),
    )
    contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deals",
        verbose_name=_("Контакт (офлайн-клиент)"),
        help_text=_("Контактное лицо клиента без входа в систему (для отправки КП)"),
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="deals_as_manager",
        verbose_name=_("Менеджер"),
        help_text=_("Ответственный менеджер RailTech"),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="assigned_deals",
        verbose_name=_("Ответственный (взял в работу)"),
        help_text=_("Кто из команды продавца ведёт эту заявку. Пусто — в общей очереди, не взята."),
    )
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Взята в работу"),
        help_text=_("Когда заявку взяли в работу — основа SLA «время до первого касания»."),
    )
    stage = models.ForeignKey(
        DealStage,
        on_delete=models.PROTECT,
        related_name="deals",
        null=True,
        db_index=True,
        verbose_name=_("Этап воронки"),
        help_text=_("Текущий этап сделки в воронке продаж"),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Название сделки"),
        help_text=_("Краткое описание сделки (опционально)"),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки"),
        help_text=_("Внутренние заметки, видны только сотрудникам"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Сделка")
        verbose_name_plural = _("Сделки")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "-created_at"], name="deal_company_created_idx"),
            models.Index(fields=["company", "stage"], name="deal_company_stage_idx"),
        ]

    def __str__(self):
        return self.title or f"Сделка #{self.pk}"

    @cached_property
    def active_quote(self):
        """Последняя версия КП. Использует prefetch cache если есть."""
        quotes = self.quotes.all()
        if "quotes" in getattr(self, "_prefetched_objects_cache", {}):
            quotes_list = list(quotes)
            return max(quotes_list, key=lambda q: q.version) if quotes_list else None
        return quotes.order_by("-version").first()

    @property
    def total_value(self) -> Decimal:
        quote = self.active_quote
        return quote.total_incl_vat if quote else Decimal("0")


class ActivityLog(models.Model):
    """Аудит-трейл системных событий и действий менеджеров."""

    LEVEL_CHOICES = [
        ("INFO", _("Информация")),
        ("SUCCESS", _("Успех")),
        ("WARNING", _("Предупреждение")),
        ("ERROR", _("Ошибка")),
    ]

    action = models.CharField(
        max_length=255,
        verbose_name=_("Действие"),
        help_text=_("Краткое описание совершённого действия"),
    )
    event_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Код события"),
        help_text=_("Машинный код события для локализуемого таймлайна (deal.created, quote.sent, ...)"),
    )
    event_params = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Параметры события"),
        help_text=_("Параметры интерполяции для перевода события на клиенте"),
    )
    detail = models.TextField(
        blank=True,
        verbose_name=_("Детали"),
        help_text=_("Подробная информация о событии"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        verbose_name=_("Пользователь"),
        help_text=_("Кто совершил действие"),
    )
    level = models.CharField(
        max_length=10,
        choices=LEVEL_CHOICES,
        default="INFO",
        verbose_name=_("Уровень"),
        help_text=_("Уровень важности события"),
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Время события"),
    )
    entity_type = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Тип сущности"),
        help_text=_("Код сущности, к которой относится запись (company, user, deal, subscription, ...)"),
    )
    entity_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("ID сущности"),
    )
    reason = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Причина"),
        help_text=_("Обязательная причина для override/force-действий"),
    )
    before_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("Состояние до"),
    )
    after_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("Состояние после"),
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_(
            "Срок действия временно́го доступа (break-glass): до этого момента оператор "
            "вправе видеть приватные данные тенанта по указанной причине. Пусто для обычных "
            "записей журнала."
        ),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="counterparty_activity",
        verbose_name=_("Компания-контрагент"),
        help_text=_("Организация, к которой относится событие (таймлайн контрагента)"),
    )
    contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        verbose_name=_("Контакт"),
    )
    deal = models.ForeignKey(
        Deal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timeline_logs",
        verbose_name=_("Сделка"),
    )

    class Meta:
        verbose_name = _("Запись активности")
        verbose_name_plural = _("Журнал активности")
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "-timestamp"]),
            models.Index(fields=["company", "-timestamp"]),
            models.Index(fields=["deal", "-timestamp"]),
        ]

    def __str__(self):
        return f"[{self.level}] {self.action}"
