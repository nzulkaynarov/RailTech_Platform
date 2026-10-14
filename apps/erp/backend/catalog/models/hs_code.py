from django.db import models
from django.utils.translation import gettext_lazy as _


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

        today = timezone.localdate()
        if self.valid_from and self.valid_from > today:
            return False
        return not (self.valid_until and self.valid_until < today)
