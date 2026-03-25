from django.db import models
from django.utils.translation import gettext_lazy as _


class AbstractLookup(models.Model):
    """
    DRY-база для всех справочных таблиц.
    Администратор добавляет записи через админку без правки кода.
    """
    code = models.CharField(
        max_length=50, unique=True, db_index=True,
        verbose_name=_("Код"),
        help_text=_("Уникальный системный код (напр. 'USD', 'FCA', 'IN_STOCK')"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Название"),
        help_text=_("Отображаемое название"),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Порядок сортировки"),
        help_text=_("Порядок отображения в интерфейсе"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Неактивные записи скрыты в формах выбора"),
    )

    class Meta:
        abstract = True
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Country(AbstractLookup):
    """Справочник стран (ISO 3166)."""
    alpha2 = models.CharField(
        max_length=2, blank=True,
        verbose_name=_("ISO Alpha-2"),
        help_text=_("Двухбуквенный код страны ISO 3166-1 (UZ, RU, CN)"),
    )
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=12.00,
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Ставка НДС по умолчанию для данной страны"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Страна")
        verbose_name_plural = _("Справочник: Страны")


class Currency(AbstractLookup):
    """Справочник валют (ISO 4217)."""
    symbol = models.CharField(
        max_length=5, blank=True,
        verbose_name=_("Символ"),
        help_text=_("Символ валюты (₽, $, €, сўм)"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Валюта")
        verbose_name_plural = _("Справочник: Валюты")


class UnitOfMeasure(AbstractLookup):
    """Единицы измерения (шт, кг, км, час)."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Единица измерения")
        verbose_name_plural = _("Справочник: Единицы измерения")


class DeliveryBasis(AbstractLookup):
    """Базисы поставок Incoterms (FCA, DAP, CIP, EXW)."""
    description = models.TextField(
        blank=True,
        verbose_name=_("Описание"),
        help_text=_("Описание условий поставки по Incoterms"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Базис поставки")
        verbose_name_plural = _("Справочник: Базисы поставок (Incoterms)")
