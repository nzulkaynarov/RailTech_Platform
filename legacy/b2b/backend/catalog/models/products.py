import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import get_public_storage, product_document_path, product_image_path
from master_data.models import UnitOfMeasure

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
        help_text=_("Внутренний артикул RailTech (генерируется автоматически)"),
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
        help_text=_("Домен каталога: ж/д техника, общие товары или услуги"),
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
        "accounts.Company",
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
        "accounts.Company",
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

    # Привязка к оборудованию (Домен 1)
    equipment_groups = models.ManyToManyField(
        "catalog.EquipmentGroup",
        blank=True,
        related_name="products",
        verbose_name=_("Группы оборудования"),
        help_text=_("Применимость к типам оборудования (обязательно для ж/д техники)"),
    )

    # Технические характеристики
    gost_drawing = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name=_("ГОСТ / Чертёж"),
        help_text=_("Номер ГОСТ или чертежа"),
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Технические параметры"),
        help_text=_("Динамические характеристики в формате ключ: значение"),
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
        if self.domain_type and getattr(self.domain_type, "code", None) == "RAILWAY_MACHINERY":
            if self.pk and not self.equipment_groups.exists():
                raise ValidationError(
                    {
                        "equipment_groups": _(
                            "Товары домена RAILWAY_MACHINERY должны быть привязаны "
                            "минимум к одной группе оборудования."
                        )
                    }
                )

    @staticmethod
    def validate_railway_equipment_groups(product):
        """
        Post-save validation: call after setting M2M equipment_groups.
        Raises ValidationError if RAILWAY_MACHINERY product has no groups.
        """
        if (
            product.domain_type
            and getattr(product.domain_type, "code", None) == "RAILWAY_MACHINERY"
            and not product.equipment_groups.exists()
        ):
            raise ValidationError(
                {
                    "equipment_groups": _(
                        "Товары домена RAILWAY_MACHINERY должны быть привязаны " "минимум к одной группе оборудования."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if not self.sku:
            prefix = self.domain_type.sku_prefix if self.domain_type else "RT"
            self.sku = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
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
    """Технические документы (паспорта, сертификаты ГОСТ)."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Товар"),
    )
    file = models.FileField(
        upload_to=product_document_path,
        storage=get_public_storage,
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
