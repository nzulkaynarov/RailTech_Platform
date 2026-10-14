from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import AbstractLookup

# ────────────────────────────────────────────
# Справочники модуля Catalog
# ────────────────────────────────────────────


class DomainType(AbstractLookup):
    """
    Домен каталога (Критический справочник).
    Seed: GENERAL_GOODS, SERVICES
    """

    GENERAL_GOODS = "GENERAL_GOODS"
    SERVICES = "SERVICES"

    sku_prefix = models.CharField(
        max_length=10,
        default="SKU",
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
