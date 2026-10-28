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
        help_text=_("Ответственный менеджер"),
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

    # Номер заявки ЗВ-ГГГГ-NNN, после принятия КП — ПР-ГГГГ-NNN с тем же NNN (SPEC-v3 §2.2, ERP-09). Выдаётся при
    # создании сделки из счётчика года под блокировкой (`sales/services/deal_numbers.py`), без пропусков.
    number = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Номер заявки"),
        help_text=_("ЗВ-ГГГГ-NNN; после принятия КП клиентом — ПР-ГГГГ-NNN (тот же NNN)"),
    )
    number_year = models.PositiveIntegerField(null=True, blank=True, editable=False, verbose_name=_("Год номера"))
    number_seq = models.PositiveIntegerField(null=True, blank=True, editable=False, verbose_name=_("NNN номера"))
    # Процесс заявки (ERP-07): v3 — заявка Платформы (резолюция и одобрение КП в EDS); legacy — начатая до Платформы.
    process = models.CharField(
        max_length=8,
        choices=[("legacy", "legacy"), ("v3", "v3")],
        default="legacy",
        verbose_name=_("Процесс заявки"),
    )
    urgency = models.CharField(
        max_length=8,
        choices=[("normal", _("Обычная")), ("urgent", _("Срочная"))],
        default="normal",
        verbose_name=_("Срочность"),
    )
    # Заявка CRM («Создать заявку», CRM-03), по которой создана сделка: ключ идемпотентности шва.
    crm_request_id = models.BigIntegerField(
        null=True, blank=True, unique=True, editable=False, verbose_name=_("Заявка CRM")
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
        constraints = [
            # Один NNN в году — одна заявка (ERP-09): последний рубеж под блокировкой счётчика.
            models.UniqueConstraint(fields=["number_year", "number_seq"], name="uniq_deal_number_year_seq"),
        ]

    def __str__(self):
        return self.title or self.number or f"Сделка #{self.pk}"

    def save(self, *args, **kwargs):
        """Новая сделка получает номер ЗВ из счётчика года в той же транзакции, что и вставка (ERP-09)."""
        if self._state.adding and not self.number_seq:
            from django.db import transaction
            from sales.services import deal_numbers

            with transaction.atomic():
                deal_numbers.assign(self)
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

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


class DealNumberCounter(models.Model):
    """Счётчик NNN номеров заявок по году (ERP-09): строка года берётся под блокировкой, номер — без пропусков."""

    year = models.PositiveIntegerField(primary_key=True, verbose_name=_("Год"))
    last_value = models.PositiveIntegerField(default=0, verbose_name=_("Последний NNN"))

    class Meta:
        verbose_name = _("Счётчик номеров заявок")
        verbose_name_plural = _("Счётчики номеров заявок")

    def __str__(self):
        return f"ЗВ {self.year}: {self.last_value}"


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
