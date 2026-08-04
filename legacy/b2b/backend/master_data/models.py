from django.db import models
from django.utils.translation import gettext_lazy as _


class AbstractLookup(models.Model):
    """
    DRY-база для всех справочных таблиц.
    Администратор добавляет записи через админку без правки кода.
    """

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
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
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Country(AbstractLookup):
    """Справочник стран (ISO 3166)."""

    alpha2 = models.CharField(
        max_length=2,
        blank=True,
        verbose_name=_("ISO Alpha-2"),
        help_text=_("Двухбуквенный код страны ISO 3166-1 (UZ, RU, CN)"),
    )
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=12.00,
        verbose_name=_("Ставка НДС (%)"),
        help_text=_("Ставка НДС по умолчанию для данной страны"),
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

    # Матрица ответственности по расходам (Incoterms 2020). Конструктор КП читает эти
    # флаги выбранного базиса и сам показывает/скрывает/делает обязательными строки
    # расходов — без хардкода «if code == 'DDP'» в коде. Данные правят матрицу.
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
        "master_data.Currency", on_delete=models.PROTECT, related_name="rates", verbose_name=_("Валюта")
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


class HSCode(models.Model):
    """Классификатор ТН ВЭД / HS — справочник товарных кодов.

    Зачем он нужен ИМЕННО как справочник, а не свободная строка в карточке: код ТН ВЭД — это
    10 цифр, и ПРИДУМАННЫЙ код хуже отсутствующего (таможня развернёт декларацию, а продавец
    узнает об этом на границе). Пока справочника нет, AI может лишь сочинять код — поэтому
    подсказка кода языковой моделью включается только поверх наполненного классификатора:
    модель ВЫБИРАЕТ из закрытого списка, а не генерирует цифры.

    Структура — иерархия самой номенклатуры: 2 знака (группа) → 4 (товарная позиция) → 6
    (субпозиция, международный уровень HS от ВТамО) → 8/10 (национальные подсубпозиции).
    Первые 6 знаков совпадают у всех стран Гармонизированной системы, дальше — национальная
    детализация, поэтому `level` хранится явно: подсказывать имеет смысл на разных уровнях.

    Ставки пошлин СОЗНАТЕЛЬНО не хранятся: они меняются чаще номенклатуры, зависят от страны
    происхождения и преференций, а их показ читался бы как таможенная консультация. Здесь —
    только код и наименование, то есть публичный классификатор.

    `valid_from` / `valid_until` — номенклатура пересматривается (ВТамО раз в пять лет,
    национальные редакции чаще), а КП и декларации должны оставаться воспроизводимыми: код,
    выведенный из обращения, не удаляется, а закрывается датой.
    """

    code = models.CharField(
        max_length=14,
        unique=True,
        db_index=True,
        verbose_name=_("Код ТН ВЭД"),
        help_text=_("Только цифры, без пробелов и разделителей (2/4/6/8/10 знаков)."),
    )
    name = models.TextField(verbose_name=_("Наименование позиции"))
    unit_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Единица измерения"),
        help_text=_("Базовая единица учёта по номенклатуре (обычно «кг»)."),
    )
    extra_unit_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Доп. единица измерения"),
        help_text=_("Дополнительная единица учёта (напр. «шт», «пар»), если предусмотрена номенклатурой."),
    )
    level = models.PositiveSmallIntegerField(
        db_index=True,
        verbose_name=_("Уровень"),
        help_text=_("Число знаков кода: 2 — группа, 4 — позиция, 6 — субпозиция, 8/10 — национальные."),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Родительская позиция"),
    )
    valid_from = models.DateField(null=True, blank=True, verbose_name=_("Действует с"))
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Действует по"),
        help_text=_("Выведенный из обращения код НЕ удаляется — старые документы должны читаться."),
    )
    source = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name=_("Источник редакции"),
        help_text=_("Откуда загружена редакция классификатора — для прослеживаемости."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Код ТН ВЭД")
        verbose_name_plural = _("Справочник: Коды ТН ВЭД")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name[:60]}"

    @property
    def is_active(self) -> bool:
        from django.utils import timezone

        today = timezone.now().date()
        if self.valid_from and self.valid_from > today:
            return False
        return not (self.valid_until and self.valid_until < today)
