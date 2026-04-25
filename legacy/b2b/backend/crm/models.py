from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
import pghistory
import pgtrigger
from master_data.models import AbstractLookup, Currency, Country
from core.storage import (
    get_private_storage, quote_pdf_path,
    contract_pdf_path, contract_signed_path,
    invoice_pdf_path, act_pdf_path, payment_proof_path,
)


# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────

class DealStage(AbstractLookup):
    """
    Этапы воронки сделки.
    Seed: DRAFT, KYC_PENDING, CALCULATING, QUOTE_SENT, CONTRACT_SIGNED, CLOSED_WON, CLOSED_LOST
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Этап сделки")
        verbose_name_plural = _("Справочник: Этапы сделок")


class QuoteStatus(AbstractLookup):
    """
    Статусы коммерческих предложений.
    Seed: DRAFT, SENT, APPROVED, REJECTED, EXPIRED
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус КП")
        verbose_name_plural = _("Справочник: Статусы КП")


# ────────────────────────────────────────────
# Основные CRM-модели
# ────────────────────────────────────────────

@pghistory.track(
    pghistory.RowEvent('deal.snapshot', row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent('deal.before_update', row=pghistory.Old, operation=pgtrigger.Update)
)
class Deal(models.Model):
    """
    Сделка — процесс переговоров с клиентом.
    Может содержать несколько версий КП (Quote).
    """
    company = models.ForeignKey(
        'accounts.Company', on_delete=models.CASCADE, related_name='deals',
        db_index=True,
        verbose_name=_("Компания"),
        help_text=_("Компания-клиент, с которой ведётся сделка"),
    )
    client = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='deals_as_client',
        verbose_name=_("Контактное лицо"),
        help_text=_("Представитель клиента в данной сделке"),
    )
    manager = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, db_index=True, related_name='deals_as_manager',
        verbose_name=_("Менеджер"),
        help_text=_("Ответственный менеджер RailTech"),
    )
    stage = models.ForeignKey(
        DealStage, on_delete=models.PROTECT, related_name='deals',
        null=True, db_index=True,
        verbose_name=_("Этап воронки"),
        help_text=_("Текущий этап сделки в воронке продаж"),
    )
    title = models.CharField(
        max_length=255, blank=True,
        verbose_name=_("Название сделки"),
        help_text=_("Краткое описание сделки (опционально)"),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Заметки"),
        help_text=_("Внутренние заметки, видны только сотрудникам"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Сделка")
        verbose_name_plural = _("Сделки")
        ordering = ['-created_at']

    def __str__(self):
        return self.title or f"Сделка #{self.pk}"

    @cached_property
    def active_quote(self):
        """Последняя версия КП. Использует prefetch cache если есть."""
        quotes = self.quotes.all()
        if 'quotes' in getattr(self, '_prefetched_objects_cache', {}):
            # Uses prefetched list — no extra SQL
            quotes_list = list(quotes)
            return max(quotes_list, key=lambda q: q.version) if quotes_list else None
        return quotes.order_by('-version').first()

    @property
    def total_value(self):
        quote = self.active_quote
        return quote.total_incl_vat if quote else Decimal('0')


@pghistory.track(
    pghistory.RowEvent('quote.snapshot', row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent('quote.before_update', row=pghistory.Old, operation=pgtrigger.Update)
)
class Quote(models.Model):
    """
    Коммерческое Предложение (КП) — версионированный документ.

    Заморозка цен: при отправке КП клиенту (status=SENT) поля цен
    в QuoteItem фиксируются. Новое изменение цен = новая версия Quote.
    """
    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='quotes',
        verbose_name=_("Сделка"),
        help_text=_("Сделка, к которой относится КП"),
    )
    version = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Версия"),
        help_text=_("Порядковый номер версии КП внутри сделки"),
    )
    status = models.ForeignKey(
        QuoteStatus, on_delete=models.PROTECT, related_name='quotes',
        null=True, blank=True,
        verbose_name=_("Статус"),
        help_text=_("Текущий статус КП (черновик, отправлено, одобрено)"),
    )
    prepared_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='prepared_quotes',
        verbose_name=_("Подготовил"),
        help_text=_("Менеджер, составивший данное КП"),
    )

    # Налоговые параметры (замороженные на момент создания КП)
    tax_country = models.ForeignKey(
        Country, on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
        verbose_name=_("Страна налогообложения"),
        help_text=_("Определяет ставку НДС для расчёта"),
    )
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=12.00,
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Зафиксированная ставка НДС на момент создания КП"),
    )

    # Агрегированные суммы (пересчитываются при сохранении позиций)
    subtotal_excl_vat = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Сумма без НДС"),
        help_text=_("Итого по всем позициям без НДС (авто-расчёт)"),
    )
    vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Сумма НДС"),
        help_text=_("Общая сумма НДС (авто-расчёт)"),
    )
    total_incl_vat = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Итого с НДС"),
        help_text=_("Полная сумма КП с учётом НДС (авто-расчёт)"),
    )

    valid_until = models.DateField(
        null=True, blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания действия коммерческого предложения"),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Примечания"),
        help_text=_("Дополнительные условия и комментарии к КП"),
    )
    pdf_file = models.FileField(
        upload_to=quote_pdf_path, storage=get_private_storage,
        null=True, blank=True,
        verbose_name=_("PDF-файл"),
        help_text=_("Сгенерированный PDF коммерческого предложения"),
    )

    frozen_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Дата заморозки цен"),
        help_text=_("Момент фиксации цен при отправке клиенту"),
    )
    approved_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Дата одобрения"),
        help_text=_("Когда КП было одобрено клиентом"),
    )
    approved_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_quotes',
        verbose_name=_("Одобрил"),
        help_text=_("Кто одобрил коммерческое предложение"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Коммерческое предложение")
        verbose_name_plural = _("Коммерческие предложения")
        unique_together = [('deal', 'version')]
        ordering = ['-version']

    def __str__(self):
        return f"КП v{self.version} — {self.deal}"

    def recalculate_totals(self):
        """
        Пересчет агрегатов из позиций через сервисный слой.
        """
        from .services import QuoteCalculationService
        return QuoteCalculationService.recalculate_quote(self.pk)


@pghistory.track(
    pghistory.RowEvent('quote_item.snapshot', row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent('quote_item.before_update', row=pghistory.Old, operation=pgtrigger.Update)
)
class QuoteItem(models.Model):
    """
    Позиция в КП — Financial Pipeline Engine.

    Расчёт:
      1. landed_cost = frozen_base_price + logistics_cost + customs_duty
      2. final_price_excl_vat = landed_cost × (1 + margin_percent / 100)
      3. line_total_incl_vat = final_price_excl_vat × quantity × (1 + vat_rate / 100)

    Для услуг (domain=SERVICES): logistics и customs = 0, прямая наценка.
    """
    quote = models.ForeignKey(
        Quote, on_delete=models.CASCADE, related_name='items',
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому относится позиция"),
    )

    # Привязка к каталогу
    product = models.ForeignKey(
        'catalog.Product', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='quote_items',
        verbose_name=_("Товар"),
        help_text=_("Эталонный товар из каталога (после Smart Match)"),
    )
    offer = models.ForeignKey(
        'catalog.SupplierOffer', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='quote_items',
        verbose_name=_("Оффер поставщика"),
        help_text=_("Конкретный оффер, из которого взята базовая цена"),
    )

    # Smart Match (сырые данные из импорта Excel)
    imported_raw_name = models.CharField(
        max_length=500, blank=True,
        verbose_name=_("Оригинальное наименование"),
        help_text=_("Строка из Excel-импорта (для нераспознанных позиций)"),
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("Количество"),
        help_text=_("Количество единиц товара"),
    )
    assigned_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Дата привязки"),
        help_text=_("Когда менеджер привязал товар/оффер к этой строке"),
    )

    # Замороженный ценовой снимок (из SupplierOffer на момент создания КП)
    frozen_base_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Базовая цена (заморожена)"),
        help_text=_("Цена поставщика, зафиксированная в момент создания КП"),
    )
    frozen_currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True,
        related_name='+',
        verbose_name=_("Валюта"),
        help_text=_("Валюта базовой цены (заморожена)"),
    )

    # Входные параметры расчёта (устанавливает менеджер)
    logistics_cost = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Логистика"),
        help_text=_("Стоимость доставки за единицу"),
    )
    customs_duty = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Таможенная пошлина"),
        help_text=_("Таможенная пошлина за единицу"),
    )
    margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(500)],
        verbose_name=_("Наценка (%)"),
        help_text=_("Процент наценки RailTech (0–500%)"),
    )

    # Вычисляемые поля (пересчитываются в save())
    landed_cost = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False,
        verbose_name=_("Себестоимость"),
        help_text=_("= базовая цена + логистика + пошлина (авто-расчёт)"),
    )
    final_price_excl_vat = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False,
        verbose_name=_("Цена без НДС"),
        help_text=_("= себестоимость × (1 + наценка%) (авто-расчёт)"),
    )

    class Meta:
        verbose_name = _("Позиция КП")
        verbose_name_plural = _("Позиции КП")

    @property
    def line_total(self):
        """Line total excl VAT = final_price_excl_vat * quantity."""
        return self.final_price_excl_vat * self.quantity

    def __str__(self):
        return self.imported_raw_name or (self.product.name if self.product else f"Позиция #{self.pk}")

    def save(self, *args, **kwargs):
        """
        Financial Pipeline: пересчёт через сервис.
        Pass skip_recalculate=True in kwargs to defer quote recalculation
        (useful for bulk operations like Excel import).
        """
        skip_recalculate = kwargs.pop('skip_recalculate', False)

        from .services import QuoteCalculationService
        # Рассчитываем поля самой позиции без немедленного сохранения (commit=False)
        QuoteCalculationService.calculate_item_prices(self, commit=False)

        super().save(*args, **kwargs)

        # Триггерим полный пересчет КП (unless explicitly deferred)
        if not skip_recalculate:
            self.quote.recalculate_totals()


# ────────────────────────────────────────────
# Коммуникации и Лиды
# ────────────────────────────────────────────

class Message(models.Model):
    """Сообщение в чате сделки."""

    MESSAGE_TYPE_CHOICES = [
        ('CHAT', _("Chat")),
        ('SYSTEM', _("System event")),
        ('NOTIFICATION', _("Notification")),
    ]

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='messages',
        db_index=True,
        verbose_name=_("Сделка"),
        help_text=_("Сделка, к которой относится сообщение"),
    )
    sender = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.CASCADE, related_name='sent_messages',
        db_index=True,
        verbose_name=_("Отправитель"),
        help_text=_("Автор сообщения"),
    )
    text = models.TextField(
        verbose_name=_("Текст сообщения"),
    )
    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPE_CHOICES,
        default='CHAT',
        db_index=True,
        verbose_name=_("Тип сообщения"),
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Время отправки"),
    )

    # Cold storage / archive metadata (Phase 6)
    is_archived = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Архивировано"),
        help_text=_("Сообщение перемещено в S3 архив"),
    )
    archived_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Дата архивации"),
    )
    archive_path = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name=_("Путь к архиву"),
        help_text=_("Путь к JSONL файлу в S3/MinIO bucket"),
    )

    class Meta:
        verbose_name = _("Сообщение")
        verbose_name_plural = _("Сообщения")
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['deal', 'timestamp']),
            models.Index(fields=['timestamp', 'is_archived']),
        ]

    def __str__(self):
        return f"{self.sender} → Сделка #{self.deal_id} ({self.timestamp:%d.%m %H:%M})"


class Lead(models.Model):
    """Заявки с публичного лендинга."""
    name = models.CharField(
        max_length=255,
        verbose_name=_("ФИО"),
        help_text=_("Имя контактного лица"),
    )
    company = models.CharField(
        max_length=255, blank=True,
        verbose_name=_("Компания"),
        help_text=_("Название организации"),
    )
    phone = models.CharField(
        max_length=50,
        verbose_name=_("Телефон"),
        help_text=_("Контактный телефон"),
    )
    email = models.EmailField(
        verbose_name=_("Email"),
        help_text=_("Электронная почта для связи"),
    )
    message = models.TextField(
        blank=True,
        verbose_name=_("Сообщение"),
        help_text=_("Текст заявки с лендинга"),
    )
    is_processed = models.BooleanField(
        default=False, db_index=True,
        verbose_name=_("Обработан"),
        help_text=_("Менеджер обработал заявку"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата получения"),
    )

    class Meta:
        verbose_name = _("Лид")
        verbose_name_plural = _("Лиды")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.company})"


class ActivityLog(models.Model):
    """Аудит-трейл системных событий и действий менеджеров."""
    LEVEL_CHOICES = [
        ('INFO', _('Информация')),
        ('SUCCESS', _('Успех')),
        ('WARNING', _('Предупреждение')),
        ('ERROR', _('Ошибка')),
    ]

    action = models.CharField(
        max_length=255,
        verbose_name=_("Действие"),
        help_text=_("Краткое описание совершённого действия"),
    )
    detail = models.TextField(
        blank=True,
        verbose_name=_("Детали"),
        help_text=_("Подробная информация о событии"),
    )
    user = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='activity_logs',
        verbose_name=_("Пользователь"),
        help_text=_("Кто совершил действие"),
    )
    level = models.CharField(
        max_length=10, choices=LEVEL_CHOICES, default='INFO',
        verbose_name=_("Уровень"),
        help_text=_("Уровень важности события"),
    )
    timestamp = models.DateTimeField(
        auto_now_add=True, db_index=True,
        verbose_name=_("Время события"),
    )
    entity_type = models.CharField(
        max_length=40, blank=True, default='', db_index=True,
        verbose_name=_("Тип сущности"),
        help_text=_("Код сущности, к которой относится запись (company, user, deal, subscription, ...)"),
    )
    entity_id = models.PositiveIntegerField(
        null=True, blank=True, db_index=True,
        verbose_name=_("ID сущности"),
    )
    reason = models.TextField(
        blank=True, default='',
        verbose_name=_("Причина"),
        help_text=_("Обязательная причина для override/force-действий"),
    )
    before_data = models.JSONField(
        null=True, blank=True,
        verbose_name=_("Состояние до"),
    )
    after_data = models.JSONField(
        null=True, blank=True,
        verbose_name=_("Состояние после"),
    )

    class Meta:
        verbose_name = _("Запись активности")
        verbose_name_plural = _("Журнал активности")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id', '-timestamp']),
        ]

    def __str__(self):
        return f"[{self.level}] {self.action}"


class QuoteItemHistory(models.Model):
    """
    Immutable audit trail for financial changes on QuoteItems.
    Every recalculation creates a snapshot of the financial state.
    """
    quote_item = models.ForeignKey(
        QuoteItem, on_delete=models.CASCADE, related_name='history',
        verbose_name=_("Позиция КП"),
        help_text=_("Позиция, по которой зафиксировано изменение"),
    )
    changed_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        verbose_name=_("Изменил"),
        help_text=_("Пользователь, инициировавший изменение"),
    )

    # Frozen snapshot of financial fields at the time of change
    frozen_base_price = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Базовая цена"),
    )
    logistics_cost = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Логистика"),
    )
    customs_duty = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Таможенная пошлина"),
    )
    margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name=_("Наценка (%)"),
    )
    landed_cost = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Себестоимость"),
    )
    final_price_excl_vat = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Цена без НДС"),
    )
    quantity = models.PositiveIntegerField(
        verbose_name=_("Количество"),
    )

    change_reason = models.CharField(
        max_length=255, blank=True,
        verbose_name=_("Причина изменения"),
        help_text=_("Комментарий к изменению (опционально)"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True,
        verbose_name=_("Дата изменения"),
    )

    class Meta:
        verbose_name = _("История изменений позиции КП")
        verbose_name_plural = _("История изменений позиций КП")
        ordering = ['-created_at']

    def __str__(self):
        return f"History #{self.pk} for {self.quote_item} at {self.created_at}"


# ────────────────────────────────────────────
# Контракты, счета, оплаты, акты — post-sale
# ────────────────────────────────────────────

class Contract(models.Model):
    """Контракт, формируемый из одобренного Quote. Двусторонняя подпись."""
    STATUS_CHOICES = [
        ('DRAFT', _('Черновик')),
        ('PENDING_CLIENT', _('Ожидает подписи клиента')),
        ('PENDING_MANAGER', _('Ожидает подписи менеджера')),
        ('SIGNED', _('Подписан сторонами')),
        ('CANCELLED', _('Отменён')),
    ]

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='contracts',
        verbose_name=_("Сделка"),
    )
    quote = models.ForeignKey(
        Quote, on_delete=models.PROTECT, related_name='contracts',
        verbose_name=_("КП-источник"),
    )
    number = models.CharField(
        max_length=64, unique=True,
        verbose_name=_("Номер контракта"),
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True,
        verbose_name=_("Статус"),
    )
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Сумма контракта"),
    )
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name=_("Валюта"),
    )

    pdf_file = models.FileField(
        upload_to=contract_pdf_path, storage=get_private_storage,
        null=True, blank=True,
        verbose_name=_("PDF контракта"),
    )
    signed_file = models.FileField(
        upload_to=contract_signed_path, storage=get_private_storage,
        null=True, blank=True,
        verbose_name=_("Подписанный скан/скан-копия"),
    )

    client_signer = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_signed_as_client',
        verbose_name=_("Подписал со стороны клиента"),
    )
    client_signed_at = models.DateTimeField(null=True, blank=True)
    manager_signer = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_signed_as_manager',
        verbose_name=_("Подписал со стороны RailTech"),
    )
    manager_signed_at = models.DateTimeField(null=True, blank=True)

    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_created',
        verbose_name=_("Создал"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Контракт")
        verbose_name_plural = _("Контракты")
        ordering = ['-created_at']

    def __str__(self):
        return f"Contract {self.number} ({self.status})"

    @property
    def is_fully_signed(self) -> bool:
        return self.status == 'SIGNED' and bool(self.client_signed_at and self.manager_signed_at)


class Invoice(models.Model):
    """Инвойс на оплату по контракту."""
    STATUS_CHOICES = [
        ('DRAFT', _('Черновик')),
        ('ISSUED', _('Выставлен')),
        ('PARTIAL', _('Частично оплачен')),
        ('PAID', _('Оплачен')),
        ('OVERDUE', _('Просрочен')),
        ('CANCELLED', _('Отменён')),
    ]

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='invoices',
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        Contract, on_delete=models.PROTECT, related_name='invoices',
        null=True, blank=True,
        verbose_name=_("Контракт"),
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер инвойса"))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='DRAFT', db_index=True,
        verbose_name=_("Статус"),
    )
    issued_at = models.DateField(null=True, blank=True, verbose_name=_("Дата выставления"))
    due_date = models.DateField(null=True, blank=True, verbose_name=_("Срок оплаты"))

    subtotal_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_incl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    pdf_file = models.FileField(
        upload_to=invoice_pdf_path, storage=get_private_storage,
        null=True, blank=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='invoices_created',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Инвойс")
        verbose_name_plural = _("Инвойсы")
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.number}"

    @property
    def balance_due(self) -> Decimal:
        return Decimal(self.total_incl_vat) - Decimal(self.amount_paid or 0)


class InvoiceItem(models.Model):
    """Позиция инвойса (копия QuoteItem на момент выставления)."""
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='items',
        verbose_name=_("Инвойс"),
    )
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total_excl_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_quote_item = models.ForeignKey(
        QuoteItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = _("Позиция инвойса")
        verbose_name_plural = _("Позиции инвойсов")

    def __str__(self):
        return f"{self.description} x{self.quantity}"


class Payment(models.Model):
    """Платёж по инвойсу."""
    METHOD_CHOICES = [
        ('BANK_TRANSFER', _('Банковский перевод')),
        ('CARD', _('Банковская карта')),
        ('CASH', _('Наличные')),
        ('OTHER', _('Другое')),
    ]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='payments',
        verbose_name=_("Инвойс"),
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='BANK_TRANSFER')
    paid_at = models.DateField(verbose_name=_("Дата платежа"))
    reference = models.CharField(
        max_length=255, blank=True,
        verbose_name=_("Референс / номер операции"),
    )
    proof_file = models.FileField(
        upload_to=payment_proof_path, storage=get_private_storage,
        null=True, blank=True,
        verbose_name=_("Подтверждение"),
    )
    recorded_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Платёж")
        verbose_name_plural = _("Платежи")
        ordering = ['-paid_at']

    def __str__(self):
        return f"Payment {self.amount} on {self.paid_at}"


class Act(models.Model):
    """Акт выполненных работ / приёма-передачи."""
    STATUS_CHOICES = [
        ('DRAFT', _('Черновик')),
        ('ISSUED', _('Выставлен')),
        ('SIGNED', _('Подписан')),
        ('CANCELLED', _('Отменён')),
    ]

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='acts',
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        Contract, on_delete=models.PROTECT, related_name='acts',
        null=True, blank=True,
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='acts',
    )
    number = models.CharField(max_length=64, unique=True, verbose_name=_("Номер акта"))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='DRAFT', db_index=True,
    )
    issued_at = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    pdf_file = models.FileField(
        upload_to=act_pdf_path, storage=get_private_storage,
        null=True, blank=True,
    )
    signed_file = models.FileField(
        upload_to=act_pdf_path, storage=get_private_storage,
        null=True, blank=True,
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Акт")
        verbose_name_plural = _("Акты")
        ordering = ['-created_at']

    def __str__(self):
        return f"Act {self.number} ({self.status})"


class Fulfillment(models.Model):
    """Исполнение сделки после подписания: отгрузка, доставка, приёмка."""
    STATUS_CHOICES = [
        ('PENDING', _('Ожидает отгрузки')),
        ('SHIPPED', _('Отгружено')),
        ('IN_TRANSIT', _('В пути')),
        ('DELIVERED', _('Доставлено')),
        ('ACCEPTED', _('Принято клиентом')),
        ('DISPUTED', _('Спорная ситуация')),
    ]

    deal = models.OneToOneField(
        Deal, on_delete=models.CASCADE, related_name='fulfillment',
        verbose_name=_("Сделка"),
    )
    contract = models.ForeignKey(
        Contract, on_delete=models.SET_NULL, null=True, blank=True, related_name='fulfillments',
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default='PENDING', db_index=True,
    )
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    tracking_number = models.CharField(max_length=128, blank=True)
    carrier = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Исполнение сделки")
        verbose_name_plural = _("Исполнение сделок")

    def __str__(self):
        return f"Fulfillment #{self.deal_id} ({self.status})"


# ────────────────────────────────────────────
# RFQ / Supplier bidding
# ────────────────────────────────────────────

class SupplierBid(models.Model):
    """Предложение поставщика по открытому RFQ."""
    STATUS_CHOICES = [
        ('DRAFT', _('Черновик')),
        ('SUBMITTED', _('Подано')),
        ('ACCEPTED', _('Принято')),
        ('REJECTED', _('Отклонено')),
        ('WITHDRAWN', _('Отозвано')),
    ]

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name='supplier_bids',
        verbose_name=_("Сделка / RFQ"),
    )
    supplier = models.ForeignKey(
        'accounts.Company', on_delete=models.CASCADE, related_name='supplier_bids',
        verbose_name=_("Поставщик"),
    )
    submitted_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default='DRAFT', db_index=True,
    )
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Предложение поставщика")
        verbose_name_plural = _("Предложения поставщиков")
        unique_together = [('deal', 'supplier')]
        ordering = ['-created_at']

    def __str__(self):
        return f"Bid {self.supplier_id} → deal {self.deal_id} ({self.status})"


class SupplierBidItem(models.Model):
    """Позиция в SupplierBid — одна за QuoteItem / спецификация."""
    bid = models.ForeignKey(
        SupplierBid, on_delete=models.CASCADE, related_name='items',
    )
    quote_item = models.ForeignKey(
        QuoteItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    product = models.ForeignKey(
        'catalog.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    description = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("Позиция bid'а")
        verbose_name_plural = _("Позиции bid'ов")

    def __str__(self):
        return f"{self.description} x{self.quantity} @ {self.unit_price}"
