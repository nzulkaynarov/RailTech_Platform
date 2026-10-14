from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import category_icon_path, get_public_storage

# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Иерархические справочники
# ────────────────────────────────────────────


class Category(models.Model):
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
        on_delete=models.CASCADE,
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

    class Meta:
        verbose_name = _("Категория")
        verbose_name_plural = _("Справочник: Категории")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


# ────────────────────────────────────────────
# Производитель / Бренд (OEM) — справочник, НЕ аккаунт
# ────────────────────────────────────────────


class Manufacturer(models.Model):
    """
    Производитель/бренд товара (OEM).

    Это СПРАВОЧНИК, а не пользователь платформы: зарубежный бренд (напр. Siemens)
    является производителем, но аккаунта не имеет. Локальный производитель может
    быть связан с платформенной компанией через ``company``. Служит каноническим
    якорем PIM: один эталонный товар одного бренда — много офферов от поставщиков.
    """

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Название"),
        help_text=_("Название бренда/производителя (OEM)"),
    )
    country = models.ForeignKey(
        "master_data.Country",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="manufacturers",
        verbose_name=_("Страна"),
        help_text=_("Страна происхождения производителя"),
    )
    website = models.URLField(
        blank=True,
        verbose_name=_("Сайт"),
        help_text=_("Официальный сайт производителя"),
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manufacturer_brands",
        verbose_name=_("Связанная компания"),
        help_text=_("Платформенная компания, если производитель зарегистрирован (местный)"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные бренды скрыты в формах выбора"),
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
        verbose_name = _("Производитель")
        verbose_name_plural = _("Справочник: Производители")
        ordering = ["name"]

    def __str__(self):
        return self.name
