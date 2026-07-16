import pghistory
import pgtrigger
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import get_private_storage, quote_pdf_path
from master_data.models import Country, Currency, DeliveryBasis

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


@pghistory.track(
    pghistory.RowEvent("quote.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("quote.before_update", row=pghistory.Old, operation=pgtrigger.Update),
)
class Quote(models.Model):
    """
    Коммерческое Предложение (КП) — версионированный документ.

    Заморозка цен: при отправке КП клиенту (status=SENT) поля цен
    в QuoteItem фиксируются. Новое изменение цен = новая версия Quote.
    """

    deal = models.ForeignKey(
        "crm.Deal",
        on_delete=models.CASCADE,
        related_name="quotes",
        verbose_name=_("Сделка"),
        help_text=_("Сделка, к которой относится КП"),
    )
    version = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Версия"),
        help_text=_("Порядковый номер версии КП внутри сделки"),
    )
    number = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        verbose_name=_("Номер КП"),
        help_text=_(
            "Человекочитаемый сквозной номер КП, выдаётся при отправке клиенту "
            "(напр. ACME-КП-2026-00001). Пусто, пока КП не отправлено."
        ),
    )
    status = models.ForeignKey(
        "crm.QuoteStatus",
        on_delete=models.PROTECT,
        related_name="quotes",
        null=True,
        blank=True,
        verbose_name=_("Статус"),
        help_text=_("Текущий статус КП (черновик, отправлено, одобрено)"),
    )
    prepared_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prepared_quotes",
        verbose_name=_("Подготовил"),
        help_text=_("Менеджер, составивший данное КП"),
    )
    seller_company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prepared_quotes",
        verbose_name=_("Компания-продавец"),
        help_text=_(
            "Компания-продавец, владеющая КП (выставляет оферту). Закрепляется при создании "
            "или при отправке на согласование за продавцом, на которого маршрутизирована "
            "сделка. Источник истины для шапки документа и цепочки согласования — НЕ выводится "
            "из основной компании автора (он мог состоять в нескольких компаниях)."
        ),
    )

    # Базис поставки (Incoterm) — «конструктор по базису»: меняет видимость строк
    # расходов и подпись итоговой цены (включая страховку / включая НДС). Расчётный
    # движок при этом один — Incoterm не меняет ЧТО считаем, лишь какие слои включены.
    delivery_basis = models.ForeignKey(
        DeliveryBasis,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quotes",
        verbose_name=_("Базис поставки (Incoterm)"),
        help_text=_("Условия поставки КП по Incoterms (FCA, CIP, DDP …)"),
    )
    # Валюта клиентского КП (ПРЕЗЕНТАЦИОННАЯ) — одна на весь КП, её видит клиент.
    # Бизнес-правило: КП клиенту по умолчанию в нац. валюте (UZS). Все агрегаты
    # (subtotal/charges/vat/total) считаются и хранятся именно в этой валюте.
    quote_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта КП"),
        help_text=_("Валюта итогового КП для клиента (по умолчанию UZS)"),
    )
    # Валюта СЕБЕСТОИМОСТИ по умолчанию для НОВЫХ позиций (UI-удобство). Реальная
    # валюта базовой цены живёт на позиции (QuoteItem.frozen_currency); это поле лишь
    # подставляется при добавлении строки, чтобы менеджер не выбирал валюту каждый раз.
    cost_currency_default = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта себестоимости по умолчанию"),
        help_text=_("Валюта базовой цены, наследуемая новыми позициями КП (UZS по умолчанию)"),
    )
    # Замороженный снимок FX-курсов к UZS, чтобы итог КП не «плавал» при движении
    # рыночного курса: {код_валюты: "курс_к_UZS"}. Заполняется движком при пересчёте
    # для каждой валюты себестоимости позиций, встреченной в КП; однажды записанный
    # курс не перезатирается рыночным (заморозка). UZS не хранится (=1).
    fx_snapshot = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Снимок курсов (FX)"),
        help_text=_("Замороженные курсы валют себестоимости к UZS на момент расчёта {код: курс}"),
    )
    # Ручное переопределение курса на уровне КП: {код_валюты: "курс"}. Имеет высший
    # приоритет — менеджер/ВЭД может зафиксировать договорной курс, который победит
    # и снимок, и рыночный курс из master_data.fx.
    fx_manual = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Ручные курсы КП (FX override)"),
        help_text=_("Договорные курсы валют к UZS, заданные вручную {код: курс} — побеждают снимок"),
    )

    # Налоговые параметры (замороженные на момент создания КП)
    tax_country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Страна налогообложения"),
        help_text=_("Определяет ставку НДС для расчёта"),
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=12.00,
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Зафиксированная ставка НДС на момент создания КП"),
    )
    # Маржа на ВЕСЬ КП (наценка на себестоимость, едина для всех позиций). Бизнес-реальность:
    # маржа ставится на КП, а не на позицию. QuoteItem.margin_percent оставлен как задел под
    # будущее позиционное переопределение, но движок применяет именно этот КП-уровневый процент.
    margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        verbose_name=_("Маржа КП (%)"),
        help_text=_("Наценка на себестоимость всех позиций (на весь КП)"),
    )

    # Агрегированные суммы (пересчитываются при сохранении позиций)
    subtotal_excl_vat = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Сумма без НДС"),
        help_text=_("Итого по всем позициям без НДС (авто-расчёт)"),
    )
    vat_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Сумма НДС"),
        help_text=_("Общая сумма НДС (авто-расчёт)"),
    )
    # Σ статей расхода уровня КП (QuoteCharge) — входят в базу до НДС (UBL document-level
    # AllowanceCharge): tax_exclusive = subtotal_excl_vat + charges_total.
    charges_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        verbose_name=_("Сумма статей расхода"),
        help_text=_("Итого по статьям расхода уровня КП (авто-расчёт, до НДС)"),
    )
    total_incl_vat = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("Итого с НДС"),
        help_text=_("Полная сумма КП с учётом НДС (авто-расчёт)"),
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания действия коммерческого предложения"),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Примечания"),
        help_text=_("Дополнительные условия и комментарии к КП"),
    )

    # Срок поставки уровня КП (ключевой коммерческий параметр). Если NULL — выводится
    # как max(сроков позиций): КП полностью поставлено, когда готова самая медленная
    # позиция. Если задан — это ручное переопределение (см. effective_delivery_lead_time).
    delivery_lead_time_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Срок поставки КП (дней)"),
        help_text=_("Срок поставки всего КП в днях. Если пусто — берётся максимум по позициям"),
    )
    delivery_note = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Условие поставки"),
        help_text=_("Уточнение по срокам/наличию («в наличии», «под заказ» и т. п.)"),
    )

    pdf_file = models.FileField(
        upload_to=quote_pdf_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("PDF-файл"),
        help_text=_("Сгенерированный PDF коммерческого предложения"),
    )

    frozen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата заморозки цен"),
        help_text=_("Момент фиксации цен при отправке клиенту"),
    )
    # Random token for an UNAUTHENTICATED public view/download of the client КП
    # projection (no margin/cost), emailed to offline/registered clients on send.
    # Minted once on send-to-client; rotate only by issuing a new КП version.
    public_access_token = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Публичный токен доступа"),
        help_text=_("Секретный токен для просмотра/скачивания КП клиентом без входа"),
    )
    # Public-link lifecycle (audit #17: an emailed КП link used to live forever, ignoring
    # valid_until / EXPIRED). Both default to the back-compatible "no restriction" so every
    # link minted before this migration keeps working: revoked=False, expires_at=NULL.
    public_token_revoked = models.BooleanField(
        default=False,
        verbose_name=_("Публичная ссылка отозвана"),
        help_text=_("Если включено — публичная ссылка на КП больше не открывается (410)"),
    )
    public_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Публичная ссылка истекает"),
        help_text=_("Явный TTL публичной ссылки. NULL — без отдельного TTL (действует срок valid_until)"),
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата одобрения"),
        help_text=_("Когда КП было одобрено клиентом"),
    )
    approved_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_quotes",
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
        unique_together = [("deal", "version")]
        ordering = ["-version"]

    def __str__(self):
        return f"КП v{self.version} — {self.deal}"

    @property
    def total_excl_vat(self):
        """Pre-VAT document total = subtotal_excl_vat + charges_total (the VAT base). Exposed as a
        property so the PDF renders the SAME Decimal value the backend taxes — the template must NOT
        recompute it with Django's `|add:` filter, which int-truncates Decimal operands (dropping
        kopecks, e.g. 2 722 500,00 + 166 361,09 → 2 888 861,00 instead of …,09, so the document
        stopped adding up while VAT/total were correct)."""
        from decimal import Decimal

        return (self.subtotal_excl_vat or Decimal("0")) + (self.charges_total or Decimal("0"))

    @property
    def effective_delivery_lead_time_days(self) -> int:
        """Срок поставки КП: ручное переопределение, иначе max(сроков позиций).

        Логика дублируется в сервисе (effective_quote_lead_time) для записи в БД на
        пересчёте; здесь — лёгкое чтение для сериализатора без сайд-эффектов.
        """
        if self.delivery_lead_time_days is not None:
            return self.delivery_lead_time_days
        # max() по позициям; 0, если позиций нет или у всех срок 0.
        return max((item.lead_time_days for item in self.items.all()), default=0)

    def recalculate_totals(self):
        """
        Пересчет агрегатов из позиций через сервисный слой.
        """
        from ..services import QuoteCalculationService

        return QuoteCalculationService.recalculate_quote(self.pk)


@pghistory.track(
    pghistory.RowEvent("quote_item.snapshot", row=pghistory.New, operation=pgtrigger.Insert | pgtrigger.Update),
    pghistory.RowEvent("quote_item.before_update", row=pghistory.Old, operation=pgtrigger.Update),
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
        "crm.Quote",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому относится позиция"),
    )

    # Привязка к каталогу
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_items",
        verbose_name=_("Товар"),
        help_text=_("Эталонный товар из каталога (после Smart Match)"),
    )
    offer = models.ForeignKey(
        "catalog.SupplierOffer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_items",
        verbose_name=_("Оффер поставщика"),
        help_text=_("Конкретный оффер, из которого взята базовая цена"),
    )

    # Smart Match (сырые данные из импорта Excel)
    imported_raw_name = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Оригинальное наименование"),
        help_text=_("Строка из Excel-импорта (для нераспознанных позиций)"),
    )
    # Канонизированное русское наименование, полученное при AI-нормализации (билингва/
    # транслитерация): «tormoznaya koloda» → «Тормозная колодка». Исходное imported_raw_name
    # НЕ трогаем — это поле служит ключом поиска по кириллическому каталогу (триграммный
    # preselect ищет и по нему). Пусто, если AI-импорт выключен или строка введена вручную.
    name_canonical = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Каноническое наименование (RU)"),
        help_text=_("Нормализованное русское наименование из AI-импорта (для поиска по каталогу)"),
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("Количество"),
        help_text=_("Количество единиц товара"),
    )
    unit = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("Единица измерения"),
        help_text=_("Ед. изм. как в заявке клиента (шт./дона/компл. и т.п.) — для отображения"),
    )
    # UBL/Peppol alignment: unit normalised to UN/ECE Recommendation 20 code
    # (H87=piece, MTR=metre, KGM=kg, TNE=tonne …) so «шт./дона/pcs» collapse to
    # one canonical value for logic, КП and any future Peppol export.
    unit_code = models.CharField(
        max_length=8,
        blank=True,
        default="",
        verbose_name=_("Код ед. изм. (UN/ECE Rec 20)"),
        help_text=_("Нормализованный код единицы измерения по UN/ECE Recommendation 20"),
    )
    # Item identification (UBL ManufacturersItemIdentification + standard/drawing ref).
    # A line can be identified by code even WITHOUT a name; «без названия» is valid if
    # mpn or gost_drawing is set. (GTIN/barcode dropped 2026-06-23 — retail concept,
    # meaningless for railway/industrial spare parts; the real identifier is MPN + ГОСТ/чертёж.)
    mpn = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name=_("Артикул / код производителя"),
        help_text=_("Manufacturer Part Number / артикул из заявки"),
    )
    gost_drawing = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name=_("ГОСТ / чертёж"),
        help_text=_("Номер ГОСТ или чертежа из заявки (канонический идентификатор детали)"),
    )
    # ТНВЭД, замороженный из Product.hs_code на момент КП (тарифы меняются — КП должно
    # быть воспроизводимым). ВЭД может переопределить per-line.
    hs_code = models.CharField(
        max_length=14,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Код ТНВЭД"),
        help_text=_("Код ТНВЭД позиции (наследуется из карточки товара, замораживается в КП)"),
    )
    note = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Примечание клиента"),
        help_text=_("Комментарий/спецификация/ссылка из заявки (Примечание, Izoh) — UBL line Note"),
    )
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Дата привязки"),
        help_text=_("Когда менеджер привязал товар/оффер к этой строке"),
    )

    # Замороженный ценовой снимок (из SupplierOffer на момент создания КП)
    frozen_base_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        # KP-04: a price can be 0 (free/included line) but never negative — a negative base
        # silently flipped landed_cost/final_price negative and distorted below_cost & margin.
        validators=[MinValueValidator(0)],
        verbose_name=_("Базовая цена (заморожена)"),
        help_text=_("Цена поставщика, зафиксированная в момент создания КП"),
    )
    frozen_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта"),
        help_text=_("Валюта базовой цены (заморожена)"),
    )

    # Входные параметры расчёта (устанавливает менеджер)
    logistics_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Логистика"),
        help_text=_("Стоимость доставки за единицу"),
    )
    customs_duty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Таможенная пошлина"),
        help_text=_("Таможенная пошлина за единицу"),
    )
    margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(500)],
        verbose_name=_("Наценка (%)"),
        help_text=_("Процент наценки RailTech (0–500%)"),
    )
    # Скидка на позицию (UBL line-level allowance, %). Применяется к цене продажи
    # строки: final_price_excl_vat = себестоимость × (1 + наценка%) × (1 − скидка%).
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Скидка (%)"),
        help_text=_("Процент скидки на позицию (0–100%)"),
    )
    # Срок поставки позиции в днях (от заказа/предоплаты). Из них КП-уровневый срок
    # выводится как максимум (Quote.effective_delivery_lead_time_days).
    lead_time_days = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Срок поставки (дней)"),
        help_text=_("Срок поставки позиции в днях от заказа/предоплаты"),
    )

    # Вычисляемые поля (пересчитываются в save())
    landed_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        verbose_name=_("Себестоимость"),
        help_text=_("= базовая цена + логистика + пошлина (авто-расчёт)"),
    )
    final_price_excl_vat = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        verbose_name=_("Цена без НДС"),
        help_text=_("= себестоимость × (1 + наценка%) (авто-расчёт)"),
    )

    class Meta:
        verbose_name = _("Позиция КП")
        verbose_name_plural = _("Позиции КП")
        ordering = ["id"]

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
        skip_recalculate = kwargs.pop("skip_recalculate", False)

        from ..services import QuoteCalculationService

        # Рассчитываем поля самой позиции без немедленного сохранения (commit=False)
        QuoteCalculationService.calculate_item_prices(self, commit=False)

        super().save(*args, **kwargs)

        # Триггерим полный пересчет КП (unless explicitly deferred)
        if not skip_recalculate:
            self.quote.recalculate_totals()


class QuoteItemHistory(models.Model):
    """
    Immutable audit trail for financial changes on QuoteItems.
    Every recalculation creates a snapshot of the financial state.
    """

    quote_item = models.ForeignKey(
        "crm.QuoteItem",
        on_delete=models.CASCADE,
        related_name="history",
        verbose_name=_("Позиция КП"),
        help_text=_("Позиция, по которой зафиксировано изменение"),
    )
    changed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Изменил"),
        help_text=_("Пользователь, инициировавший изменение"),
    )

    # Frozen snapshot of financial fields at the time of change
    frozen_base_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("Базовая цена"),
    )
    logistics_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("Логистика"),
    )
    customs_duty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("Таможенная пошлина"),
    )
    margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name=_("Наценка (%)"),
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name=_("Скидка (%)"),
    )
    landed_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("Себестоимость"),
    )
    final_price_excl_vat = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("Цена без НДС"),
    )
    quantity = models.PositiveIntegerField(
        verbose_name=_("Количество"),
    )

    change_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Причина изменения"),
        help_text=_("Комментарий к изменению (опционально)"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Дата изменения"),
    )

    class Meta:
        verbose_name = _("История изменений позиции КП")
        verbose_name_plural = _("История изменений позиций КП")
        ordering = ["-created_at"]

    def __str__(self):
        return f"History #{self.pk} for {self.quote_item} at {self.created_at}"
