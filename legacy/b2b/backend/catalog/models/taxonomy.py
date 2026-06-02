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
        max_length=255,
        db_index=True,
        verbose_name=_("Название"),
        help_text=_("Название группы/типа оборудования"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
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
        max_length=500,
        blank=True,
        editable=False,
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
                from django.db.models import F
                from django.db.models.functions import Concat, Length, Substr, Value

                # Only update direct descendants (paths that start with "old_path / ")
                # Use Concat(new_path, Substr(...)) instead of Replace to avoid
                # accidentally replacing substrings in unrelated parts of the path
                old_prefix = f"{old_path} / "
                descendants = EquipmentGroup.objects.filter(cached_path__startswith=old_prefix)
                descendants.update(
                    cached_path=Concat(Value(f"{new_path} / "), Substr(F("cached_path"), Length(Value(old_prefix)) + 1))
                )

    @property
    def full_path(self):
        return self.cached_path
