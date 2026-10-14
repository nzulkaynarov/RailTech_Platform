from django.db import models
from django.utils.translation import gettext_lazy as _

from .lookups import AbstractLookup


class Country(AbstractLookup):
    """Справочник стран по ISO 3166-1.

    Канонический ключ — `code` = **alpha-2** («RU», «UZ»): на него смотрят FK (`Company.country`,
    `Quote.tax_country`) и импорт компаний по коду, поэтому семантика ключа неприкосновенна.
    Остальные представления того же стандарта хранятся рядом, а не выводятся на лету: alpha-3
    печатается в документах, а **numeric** — это язык таможенных систем (тарифные сервисы ГТК РУз
    принимают именно 643/860/156). Отдельного «кода под интеграцию» нет и не должно быть: поле
    стандартное, а несовпадения конкретного источника со стандартом лечатся таблицей
    соответствия в самой интеграции.

    `vat_rate` НЕОБЯЗАТЕЛЕН и по умолчанию НЕИЗВЕСТЕН (NULL).
    """

    alpha2 = models.CharField(
        max_length=2,
        blank=True,
        verbose_name=_("ISO Alpha-2"),
        help_text=_("Двухбуквенный код страны ISO 3166-1 (UZ, RU, CN) — дублирует `code`"),
    )
    alpha3 = models.CharField(
        max_length=3,
        blank=True,
        default="",
        verbose_name=_("ISO Alpha-3"),
        help_text=_("Трёхбуквенный код ISO 3166-1 (UZB, RUS, CHN) — используется в документах"),
    )
    iso_numeric = models.CharField(
        max_length=3,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("ISO цифровой код"),
        help_text=_("Цифровой код ISO 3166-1 (860, 643, 156) — язык таможенных систем"),
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Выверенная ставка НДС страны; пусто = неизвестна (не выдумываем)"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Страна")
        verbose_name_plural = _("Справочник: Страны")


class Currency(AbstractLookup):
    """Справочник валют (ISO 4217)."""

    symbol = models.CharField(
        max_length=5,
        blank=True,
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

    # Матрица ответственности по расходам (Incoterms 2020).
    seller_pays_freight = models.BooleanField(
        default=False,
        verbose_name=_("Продавец оплачивает фрахт"),
        help_text=_("Основная перевозка лежит на продавце (C- и D-термы)"),
    )
    seller_pays_insurance = models.BooleanField(
        default=False,
        verbose_name=_("Продавец оплачивает страхование"),
        help_text=_("Продавец несёт транзитный риск/страхование груза (CIF, CIP, D-термы)"),
    )
    seller_pays_import = models.BooleanField(
        default=False,
        verbose_name=_("Продавец оплачивает импортную растаможку"),
        help_text=_("Импортная пошлина/оформление/НДС на стороне продавца (только DDP)"),
    )
    seller_pays_delivery = models.BooleanField(
        default=False,
        verbose_name=_("Продавец оплачивает доставку до места"),
        help_text=_("Доставка до названного места назначения (D-термы)"),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Базис поставки")
        verbose_name_plural = _("Справочник: Базисы поставок (Incoterms)")


class ExchangeRate(models.Model):
    """Курс валюты к UZS на дату. Источник: ЦБ РУз (авто, Celery beat) или ручной (MANUAL).

    Соглашение: 1 единица `currency` = `rate_to_uzs` сум. UZS к самому себе не хранится (=1).
    КП замораживает нужные курсы снимком на момент создания (см. Quote FX-snapshot).
    """

    currency = models.ForeignKey(
        "core.Currency", on_delete=models.PROTECT, related_name="rates", verbose_name=_("Валюта")
    )
    rate_to_uzs = models.DecimalField(
        max_digits=18, decimal_places=6, verbose_name=_("Курс к UZS"), help_text=_("Сколько сум за 1 единицу валюты")
    )
    rate_date = models.DateField(verbose_name=_("Дата курса"))
    source = models.CharField(max_length=16, default="CBU", verbose_name=_("Источник"), help_text=_("CBU или MANUAL"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Курс валюты")
        verbose_name_plural = _("Справочник: Курсы валют")
        ordering = ["-rate_date", "currency__code"]
        constraints = [
            models.UniqueConstraint(fields=["currency", "rate_date"], name="uniq_exchange_rate_ccy_date"),
        ]

    def __str__(self):
        return f"{self.currency.code} = {self.rate_to_uzs} UZS @ {self.rate_date}"
