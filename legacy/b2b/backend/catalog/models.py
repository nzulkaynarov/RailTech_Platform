from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import uuid
from master_data.models import AbstractLookup, Currency, UnitOfMeasure, DeliveryBasis
from core.storage import (
    get_public_storage,
    product_image_path, product_document_path, category_icon_path,
)


# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────

class DomainType(AbstractLookup):
    """
    Домен каталога (Критический справочник).
    Seed: RAILWAY_MACHINERY, GENERAL_GOODS, SERVICES
    """
    RAILWAY_MACHINERY = 'RAILWAY_MACHINERY'
    GENERAL_GOODS = 'GENERAL_GOODS'
    SERVICES = 'SERVICES'

    sku_prefix = models.CharField(
        max_length=10, default='RT',
        verbose_name=_("Префикс артикула"),
        help_text=_("Префикс для авто-генерации SKU товаров этого домена"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип домена")
        verbose_name_plural = _("Справочник: Типы доменов")


class ProductStatus(AbstractLookup):
    """
    Жизненный цикл товара.
    Seed: DRAFT, PUBLISHED, ARCHIVED
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус товара")
        verbose_name_plural = _("Справочник: Статусы товаров")


class StockStatus(AbstractLookup):
    """
    Статус наличия.
    Seed: IN_STOCK, ON_ORDER, EXPECTED, OUT_OF_STOCK
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус наличия")
        verbose_name_plural = _("Справочник: Статусы наличия")


# ────────────────────────────────────────────
# Иерархические справочники
# ────────────────────────────────────────────

class Category(models.Model):
    """
    Иерархическое дерево категорий товаров.
    Примеры: Запчасти → Подшипники → Роликовые подшипники
    """
    name = models.CharField(
        max_length=255, db_index=True,
        verbose_name=_("Название"),
        help_text=_("Название категории товаров"),
    )
    domain_type = models.ForeignKey(
        DomainType, on_delete=models.PROTECT, related_name='categories',
        null=True, blank=True,
        verbose_name=_("Тип домена"),
        help_text=_("Домен каталога, к которому относится категория"),
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children',
        verbose_name=_("Родительская категория"),
        help_text=_("Вышестоящая категория в иерархии"),
    )
    icon = models.ImageField(
        upload_to=category_icon_path, storage=get_public_storage,
        null=True, blank=True,
        verbose_name=_("Иконка"),
        help_text=_("Иконка категории для отображения в каталоге"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок сортировки"),
        help_text=_("Порядок отображения среди категорий одного уровня"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активна"),
        help_text=_("Неактивные категории скрыты в каталоге"),
    )

    class Meta:
        verbose_name = _("Категория")
        verbose_name_plural = _("Справочник: Категории")
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class EquipmentGroup(models.Model):
    """
    Иерархия типов оборудования (Строгий учет — Домен 1).

    Пример дерева (seed):
      Подвижной состав
      ├── Локомотивы
      │   ├── Тепловозы
      │   │   ├── ТЭМ18ДМ
      │   │   ├── ТЭМ2
      │   │   └── ТГМ6
      │   └── Электровозы
      │       ├── ВЛ80
      │       └── ЭП1М
      ├── Вагоны
      │   ├── Грузовые
      │   └── Пассажирские
      └── Путевая техника
          ├── Дефектоскопы
          └── Шпалоподбивочные машины
    """
    name = models.CharField(
        max_length=255, db_index=True,
        verbose_name=_("Название"),
        help_text=_("Название группы/типа оборудования"),
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children',
        verbose_name=_("Родительская группа"),
        help_text=_("Вышестоящая группа в иерархии оборудования"),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Описание"),
        help_text=_("Описание группы оборудования"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок сортировки"),
    )
    cached_path = models.CharField(
        max_length=500, blank=True, editable=False,
        verbose_name=_("Полный путь"),
        help_text=_("Авто-генерируемый путь в иерархии (только чтение)"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активна"),
        help_text=_("Неактивные группы скрыты в формах выбора"),
    )

    class Meta:
        verbose_name = _("Группа оборудования")
        verbose_name_plural = _("Группы оборудования")
        ordering = ["cached_path"]

    def __str__(self):
        return self.cached_path or self.name

    def save(self, *args, **kwargs):
        """
        Optimized Path Update (O(1) query for descendants).
        Replaces recursive .save() calls with a bulk update.
        """
        from django.db import transaction

        old_path = self.cached_path
        new_path = f"{self.parent.cached_path} / {self.name}" if self.parent else self.name

        # Check if the structure actually changed
        path_changed = old_path != new_path
        self.cached_path = new_path

        with transaction.atomic():
            super().save(*args, **kwargs)

            # If path changed, update ALL descendants in one SQL query
            if path_changed and self.pk and old_path:
                from django.db.models.functions import Concat, Substr, Length, Value
                from django.db.models import F

                # Only update direct descendants (paths that start with "old_path / ")
                # Use Concat(new_path, Substr(...)) instead of Replace to avoid
                # accidentally replacing substrings in unrelated parts of the path
                old_prefix = f"{old_path} / "
                descendants = EquipmentGroup.objects.filter(
                    cached_path__startswith=old_prefix)
                descendants.update(
                    cached_path=Concat(
                        Value(f"{new_path} / "),
                        Substr(F('cached_path'), Length(Value(old_prefix)) + 1)
                    )
                )

    @property
    def full_path(self):
        return self.cached_path


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
        max_length=255, db_index=True,
        verbose_name=_("Наименование"),
        help_text=_("Полное наименование товара"),
    )
    sku = models.CharField(
        max_length=50, unique=True, db_index=True, blank=True,
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
        DomainType, on_delete=models.PROTECT, related_name='products',
        null=True, blank=True, db_index=True,
        verbose_name=_("Тип домена"),
        help_text=_("Домен каталога: ж/д техника, общие товары или услуги"),
    )
    status = models.ForeignKey(
        ProductStatus, on_delete=models.PROTECT, related_name='products',
        null=True, blank=True,
        verbose_name=_("Статус"),
        help_text=_("Статус жизненного цикла: черновик, опубликован, архив"),
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products',
        verbose_name=_("Категория"),
        help_text=_("Категория товара в иерархии каталога"),
    )
    uom = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, null=True, blank=True,
        related_name='products',
        verbose_name=_("Единица измерения"),
        help_text=_("Базовая единица измерения (шт, кг, м)"),
    )
    manufacturer = models.ForeignKey(
        'accounts.Company', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='manufactured_products',
        verbose_name=_("Производитель"),
        help_text=_("Компания-производитель (OEM)"),
    )

    # Привязка к оборудованию (Домен 1)
    equipment_groups = models.ManyToManyField(
        EquipmentGroup, blank=True, related_name='products',
        verbose_name=_("Группы оборудования"),
        help_text=_("Применимость к типам оборудования (обязательно для ж/д техники)"),
    )

    # Технические характеристики
    gost_drawing = models.CharField(
        max_length=100, blank=True, db_index=True,
        verbose_name=_("ГОСТ / Чертёж"),
        help_text=_("Номер ГОСТ или чертежа"),
    )
    specifications = models.JSONField(
        default=dict, blank=True,
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
        ordering = ['name']

    def __str__(self):
        return f"{self.name} [{self.sku}]" if self.sku else self.name

    def clean(self):
        super().clean()
        if self.domain_type and getattr(self.domain_type, 'code', None) == 'RAILWAY_MACHINERY':
            if self.pk and not self.equipment_groups.exists():
                raise ValidationError({
                    "equipment_groups": _(
                        "Товары домена RAILWAY_MACHINERY должны быть привязаны "
                        "минимум к одной группе оборудования."
                    )
                })

    @staticmethod
    def validate_railway_equipment_groups(product):
        """
        Post-save validation: call after setting M2M equipment_groups.
        Raises ValidationError if RAILWAY_MACHINERY product has no groups.
        """
        if (product.domain_type
                and getattr(product.domain_type, 'code', None) == 'RAILWAY_MACHINERY'
                and not product.equipment_groups.exists()):
            raise ValidationError({
                "equipment_groups": _(
                    "Товары домена RAILWAY_MACHINERY должны быть привязаны "
                    "минимум к одной группе оборудования."
                )
            })

    def save(self, *args, **kwargs):
        if not self.sku:
            prefix = self.domain_type.sku_prefix if self.domain_type else "RT"
            self.sku = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
        self.full_clean()
        super().save(*args, **kwargs)


# ────────────────────────────────────────────
# Оффер поставщика (Product + Company = Price)
# ────────────────────────────────────────────

class SupplierOffer(models.Model):
    """
    Коммерческое предложение поставщика на конкретный товар.

    Один Product может иметь несколько офферов от разных поставщиков.
    Именно отсюда менеджер берет цены при создании КП (Quote).
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='offers',
        verbose_name=_("Товар"),
        help_text=_("Эталонный товар из каталога PIM"),
    )
    supplier = models.ForeignKey(
        'accounts.Company', on_delete=models.CASCADE, related_name='supplier_offers',
        verbose_name=_("Поставщик"),
        help_text=_("Компания-поставщик"),
    )
    supplier_sku = models.CharField(
        max_length=100, blank=True,
        verbose_name=_("Артикул поставщика"),
        help_text=_("Внутренний номер товара у поставщика"),
    )

    # Коммерческие условия
    base_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name=_("Базовая цена"),
        help_text=_("Цена поставщика за единицу (FCA/EXW)"),
    )
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, related_name='offers',
        null=True, blank=True,
        verbose_name=_("Валюта"),
        help_text=_("Валюта базовой цены"),
    )
    delivery_basis = models.ForeignKey(
        DeliveryBasis, on_delete=models.PROTECT, related_name='offers',
        null=True, blank=True,
        verbose_name=_("Базис поставки"),
        help_text=_("Условия поставки по Incoterms (FCA, DAP, EXW)"),
    )
    stock_status = models.ForeignKey(
        StockStatus, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='offers',
        verbose_name=_("Статус наличия"),
        help_text=_("Текущий статус наличия у поставщика"),
    )
    delivery_lead_time = models.CharField(
        max_length=100, blank=True,
        verbose_name=_("Срок поставки"),
        help_text=_("Ориентировочный срок поставки (напр. '14-21 дн.')"),
    )
    min_order_qty = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Мин. заказ"),
        help_text=_("Минимальное количество для заказа"),
    )

    # Срок действия оффера
    valid_from = models.DateField(
        null=True, blank=True,
        verbose_name=_("Действует с"),
        help_text=_("Дата начала действия предложения"),
    )
    valid_until = models.DateField(
        null=True, blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Дата окончания действия предложения"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные офферы не отображаются при выборе"),
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
        verbose_name = _("Оффер поставщика")
        verbose_name_plural = _("Каталог: Офферы поставщиков")
        unique_together = [('product', 'supplier')]
        ordering = ['base_price']

    def __str__(self):
        return f"{self.product.name} | {self.supplier.name} | {self.base_price} {self.currency}"


# ────────────────────────────────────────────
# Медиа-файлы товаров
# ────────────────────────────────────────────

class ProductImage(models.Model):
    """Галерея фото товара."""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images',
        verbose_name=_("Товар"),
    )
    image = models.ImageField(
        upload_to=product_image_path, storage=get_public_storage,
        null=True, blank=True,
        verbose_name=_("Изображение"),
        help_text=_("Файл фотографии товара"),
    )
    image_url = models.URLField(
        max_length=500, null=True, blank=True,
        verbose_name=_("URL изображения"),
        help_text=_("Внешняя ссылка на фото (если файл не загружен)"),
    )
    is_main = models.BooleanField(
        default=False,
        verbose_name=_("Главное фото"),
        help_text=_("Отображается первым в карточке товара"),
    )
    alt_text = models.CharField(
        max_length=255, blank=True,
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
        ordering = ['-is_main', 'sort_order']

    def __str__(self):
        return f"Image for {self.product.name}"


class ProductDocument(models.Model):
    """Технические документы (паспорта, сертификаты ГОСТ)."""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='documents',
        verbose_name=_("Товар"),
    )
    file = models.FileField(
        upload_to=product_document_path, storage=get_public_storage,
        null=True, blank=True,
        verbose_name=_("Файл"),
        help_text=_("Загруженный документ (PDF, DOCX)"),
    )
    file_url = models.URLField(
        max_length=500, null=True, blank=True,
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
