from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.constants import TrackingClass
from core.models.master_data import LocalizedNames
from core.storage import category_icon_path, get_public_storage

# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Иерархические справочники
# ────────────────────────────────────────────


class Category(LocalizedNames, models.Model):
    """
    Иерархическое дерево категорий товаров.
    Примеры: Запчасти → Подшипники → Роликовые подшипники
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Название"),
        help_text=_("Название категории товаров"),
    )
    domain_type = models.ForeignKey(
        "catalog.DomainType",
        on_delete=models.PROTECT,
        related_name="categories",
        null=True,
        blank=True,
        verbose_name=_("Тип домена"),
        help_text=_("Домен каталога, к которому относится категория"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Родительская категория"),
        help_text=_("Вышестоящая категория в иерархии"),
    )
    icon = models.ImageField(
        upload_to=category_icon_path,
        storage=get_public_storage,
        null=True,
        blank=True,
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
    # ADR-0021 (L0-3): прослеживаемость — данные категории, товар наследует.
    tracking = models.CharField(
        max_length=8,
        choices=TrackingClass.choices,
        default=TrackingClass.NONE,
        verbose_name=_("Учёт единиц"),
        help_text=_("Серийный — каждая единица, партия — номер и срок годности, только количество — без номеров"),
    )
    requires_conformity_doc = models.BooleanField(
        default=False,
        verbose_name=_("Нужен документ соответствия"),
        help_text=_("При приёмке — № сертификата или декларации и срок действия"),
    )

    class Meta:
        verbose_name = _("Категория")
        verbose_name_plural = _("Справочник: Категории")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


# ────────────────────────────────────────────
# Бренд (OEM) — справочник, НЕ аккаунт (ADR-0028 п. 4)
# ────────────────────────────────────────────


class Manufacturer(LocalizedNames, models.Model):
    """
    Бренд — марка на товаре (OEM); в интерфейсе — справочник «Бренды» (ADR-0028 п. 4).

    Это СПРАВОЧНИК, а не контрагент: у бренда без договора с заводом (напр. SKF) компании нет.
    Завод, с которым работаем, — компания ERP с ролью «Изготовитель» (тип MANUFACTURER); у бренда
    на неё ссылка ``company``. Служит каноническим якорем PIM: один эталонный товар одного бренда —
    много офферов от поставщиков. Имя модели прежнее: переименование таблицы ничего не даёт.
    """

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Название"),
        help_text=_("Название бренда (OEM)"),
    )
    country = models.ForeignKey(
        "core.Country",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="manufacturers",
        verbose_name=_("Страна"),
        help_text=_("Страна бренда"),
    )
    website = models.URLField(
        blank=True,
        verbose_name=_("Сайт"),
        help_text=_("Официальный сайт бренда"),
    )
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manufacturer_brands",
        verbose_name=_("Изготовитель"),
        help_text=_("Компания-изготовитель, если с заводом работаем; у компании роль «Изготовитель»"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные бренды скрыты в формах выбора"),
    )
    # План 3.8: бренды — справочником файлом, порядок как у остальных справочников.
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_("Порядок сортировки"))
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Бренд")
        verbose_name_plural = _("Справочник: Бренды")
        ordering = ["name"]

    def __str__(self):
        return self.name
