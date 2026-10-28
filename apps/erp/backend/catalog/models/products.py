import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.constants import FulfillmentPolicy, PriceVisibility
from core.storage import get_private_storage, get_public_storage, product_document_path, product_image_path
from master_data.models import Currency, UnitOfMeasure

# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Эталонный товар (PIM)
# ────────────────────────────────────────────


class Product(models.Model):
    """
    Эталонная карточка товара (Product Information Management).

    Содержит ТОЛЬКО справочные данные: что это за товар, какие у него
    характеристики, кто производитель, к какому оборудованию относится.

    Коммерческие условия (цена, наличие, сроки) вынесены в SupplierOffer.
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Наименование"),
        help_text=_("Полное наименование товара"),
    )
    sku = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        blank=True,
        verbose_name=_("Артикул (SKU)"),
        help_text=_("Внутренний артикул (генерируется автоматически)"),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Описание"),
        help_text=_("Подробное описание товара для каталога"),
    )

    # Справочные связи
    domain_type = models.ForeignKey(
        "catalog.DomainType",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Тип домена"),
        help_text=_("Домен каталога: товары или услуги"),
    )
    status = models.ForeignKey(
        "catalog.ProductStatus",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        verbose_name=_("Статус"),
        help_text=_("Статус жизненного цикла: черновик, опубликован, архив"),
    )
    category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("Категория"),
        help_text=_("Категория товара в иерархии каталога"),
    )
    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("Единица измерения"),
        help_text=_("Базовая единица измерения (шт, кг, м)"),
    )
    # DEPRECATED (F5.2): conflated two roles — tenancy/ownership AND OEM. Ownership
    # moved to `owner_company`, OEM moved to `brand` (catalog.Manufacturer). No code
    # reads/writes this anymore; kept nullable for one release, dropped in a follow-up
    # migration (roadmap contract-phase). Do NOT use in new code.
    manufacturer = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manufactured_products",
        verbose_name=_("Производитель (DEPRECATED)"),
        help_text=_("УСТАРЕЛО — заменено на owner_company (владелец) + brand (OEM)."),
    )
    # Tenancy: the platform company that owns/created this catalog card (the seller).
    # Drives the "see my own unpublished products" scoping; NOT the OEM (that's `brand`).
    owner_company = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_products",
        db_index=True,
        verbose_name=_("Компания-владелец"),
        help_text=_("Продавец/поставщик, создавший карточку (мультитенантность PIM)."),
    )
    brand = models.ForeignKey(
        "catalog.Manufacturer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("Производитель (бренд)"),
        help_text=_("Бренд/производитель из справочника (OEM). Канонический для PIM."),
    )
    manufacturer_part_number = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        verbose_name=_("Артикул производителя (MPN)"),
        help_text=_("Заводской артикул. Ключ дедупликации PIM: бренд + артикул."),
    )

    # Технические характеристики
    gost_drawing = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name=_("ГОСТ / Чертёж"),
        help_text=_("Номер ГОСТ или чертежа"),
    )
    # ТНВЭД / HS-код — постоянный дом кода товара (PIM). Один раз внесли в карточку →
    # больше не ищем заново. КП наследует и замораживает его в QuoteItem.hs_code.
    hs_code = models.CharField(
        max_length=14,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Код ТНВЭД"),
        help_text=_("Код товарной номенклатуры ВЭД (ТНВЭД/HS). Хранится в карточке, чтобы не искать заново."),
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Технические параметры"),
        help_text=_("Динамические характеристики в формате ключ: значение"),
    )

    # ── Опубликованный слой (M1-ERP-07, BUSINESS §10.1) ──────────────────────────
    #
    # Одна карточка — два слоя. Внутренний (поставщики, закупочные цены, остатки количеством,
    # себестоимость) живёт в предложениях поставщиков и никогда не покидает бэк-офис.
    # Опубликованный — то, что видят клиент и бот: имя, описание, характеристики, единица,
    # фото, цена-витрина ИЛИ «по запросу», наличие как статус. Его отдаёт ТОЛЬКО
    # `catalog.published.project()` — белым списком полей.
    fulfillment_policy = models.CharField(
        max_length=16,
        choices=FulfillmentPolicy.choices,
        blank=True,
        default="",
        verbose_name=_("Политика исполнения"),
        help_text=_("Только для услуг: фикс, по этапам или по времени. У товара — пусто."),
    )
    price_visibility = models.CharField(
        max_length=16,
        choices=PriceVisibility.choices,
        blank=True,
        default="",
        verbose_name=_("Видимость цены"),
        help_text=_("Пусто — по политике каталога компании (по умолчанию «по запросу»)."),
    )
    list_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_("Цена-витрина"),
        help_text=_("Цена для клиента в кабинете. Не себестоимость и не цена поставщика."),
    )
    list_price_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Валюта цены-витрины"),
    )
    # НДС позиции, % (D2-3, SPEC-v3 §7.4): пусто — ставка компании по умолчанию (`CompanySettings.default_vat_rate`).
    # Во внутренний слой: опубликованный слой (`catalog.published`, белый список) поле не отдаёт.
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_("НДС, %"),
        help_text=_("Пусто — ставка компании по умолчанию."),
    )

    # ── Провенанс кандидата (волна A номенклатуры) ───────────────────────────────
    #
    # Позиция, которой нет в каталоге, — норма для рынка запчастей по чертежам (SAP зовёт это
    # one-time material). Но она не должна оставаться сиротой: замер 03-08 показал, что 90 из
    # 98 строк КП шли мимо каталога, а введённые продавцом ТН ВЭД и сроки умирали вместе с КП.
    #
    # Эталон — catalog enablement из Ariba/Coupa: free-text позиция уходит в очередь, и из
    # повторяющихся рождаются каталожные карточки. Поэтому карточка помнит, ОТКУДА пришла и
    # СКОЛЬКО раз её спрашивали: очередь сортируется по спросу, и продавец сначала описывает
    # то, что окупится быстрее.
    source_deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_candidates",
        verbose_name=_("Заявка-источник"),
        help_text=_("Заявка, из строки которой родилась карточка (провенанс кандидата)."),
    )
    demand_count = models.PositiveIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Сколько раз спрашивали"),
        help_text=_("Число КП, где встретилась эта позиция. Очередь наполнения сортируется по нему."),
    )
    last_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Последний запрос"),
        help_text=_("Когда позицию спрашивали в последний раз."),
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
        verbose_name = _("Товар (PIM)")
        verbose_name_plural = _("Каталог: Товары (PIM)")
        ordering = ["name"]
        # NOTE: GIN trigram indexes for Smart Match (TrigramSimilarity on name and
        # gost_drawing) are created in migration 0006 via raw SQL, NOT declared here.
        # They depend on the pg_trgm extension; keeping them out of model state means
        # the test suite's --nomigrations schema build does not require the extension.

    def __str__(self):
        return f"{self.name} [{self.sku}]" if self.sku else self.name

    def clean(self):
        super().clean()
        # Цена без валюты — не цена (контракт портала: Money = amount + currency).
        if self.list_price is not None and self.list_price_currency_id is None:
            from django.core.exceptions import ValidationError

            raise ValidationError({"list_price_currency": "LIST_PRICE_CURRENCY_REQUIRED"})

    @property
    def is_service(self) -> bool:
        return getattr(self.domain_type, "code", None) == "SERVICES"

    def _normalize_fulfillment_policy(self, update_fields) -> None:
        """Политика исполнения следует за типом карточки, а не за формой.

        Услуга без политики получает «фикс» (самый частый случай, Odoo: fixed price по
        умолчанию), у товара политика всегда пустая — иначе смена «услуга → товар» оставляла бы
        висящие «этапы». Частичное сохранение без `fulfillment_policy` в `update_fields` поле не
        трогает: его значение туда не попало бы.
        """
        if update_fields is not None and "fulfillment_policy" not in update_fields:
            return
        if self.is_service:
            self.fulfillment_policy = self.fulfillment_policy or FulfillmentPolicy.FIXED
        else:
            self.fulfillment_policy = ""

    def save(self, *args, **kwargs):
        # Статус — часть жизненного цикла, а не необязательный ярлык: у 5 из 8 карточек он был
        # пуст, и «черновик / опубликован / архив» существовал только на бумаге. Новая карточка
        # рождается ЧЕРНОВИКОМ (Akeneo/Pimcore: запись входит в workflow, а не появляется сразу
        # в канале). `get`, а не `get_or_create` — справочник создаётся миграцией (Rule 1), и
        # молчаливое досоздание маскировало бы незапущенную миграцию.
        if self.status_id is None:
            from catalog.models import ProductStatus

            self.status = ProductStatus.objects.get(code="DRAFT")
        if not self.sku:
            prefix = self.domain_type.sku_prefix if self.domain_type else "RT"
            self.sku = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
        self._normalize_fulfillment_policy(kwargs.get("update_fields"))
        self.full_clean()
        super().save(*args, **kwargs)


# ────────────────────────────────────────────
# Медиа-файлы товаров
# ────────────────────────────────────────────


class ProductImage(models.Model):
    """Галерея фото товара."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("Товар"),
    )
    image = models.ImageField(
        upload_to=product_image_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Изображение"),
        help_text=_("Файл фотографии товара"),
    )
    image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name=_("URL изображения"),
        help_text=_("Внешняя ссылка на фото (если файл не загружен)"),
    )
    is_main = models.BooleanField(
        default=False,
        verbose_name=_("Главное фото"),
        help_text=_("Отображается первым в карточке товара"),
    )
    alt_text = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Alt-текст"),
        help_text=_("Альтернативный текст для SEO и доступности"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок сортировки"),
    )

    class Meta:
        verbose_name = _("Фото товара")
        verbose_name_plural = _("Фото товаров")
        ordering = ["-is_main", "sort_order"]

    def __str__(self):
        return f"Image for {self.product.name}"


class ProductDocument(models.Model):
    """Технические документы (паспорта, сертификаты ГОСТ).

    Файл — в приватном бакете `erp-private` (S0-9): документ товара не публичный, `/media/products/<id>/docs/*`
    не открывается; сотрудник скачивает его через `GET catalog/products/{id}/download-document/{doc_id}/`."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Товар"),
    )
    file = models.FileField(
        upload_to=product_document_path,
        storage=get_private_storage,
        null=True,
        blank=True,
        verbose_name=_("Файл"),
        help_text=_("Загруженный документ (PDF, DOCX)"),
    )
    file_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name=_("URL документа"),
        help_text=_("Внешняя ссылка на документ (если файл не загружен)"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Название документа"),
        help_text=_("Напр: Паспорт изделия, Сертификат ГОСТ"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата загрузки"),
    )

    class Meta:
        verbose_name = _("Документ товара")
        verbose_name_plural = _("Документы товаров")

    def __str__(self):
        return f"{self.name} — {self.product.name}"
