"""Рамка договора по шаблону (ПК-1): название и подписи сторон берутся у самого шаблона, а не зашиты «поставкой».

Договор поставки печатает «Договор поставки», «Поставщик» и «Покупатель». Любой другой шаблон — договор о партнёрстве,
соглашение о неразглашении, оферта, услуги — печатает своё название и нейтральные подписи сторон: «Компания» и
«Партнёр» или «Клиент», а без вида контрагента — «Сторона 1» и «Сторона 2». Шаблона нет (прежний путь из кода) — рамка
поставки, как раньше.
"""

from dataclasses import dataclass

from django.utils.translation import gettext as _

SUPPLY = "supply"


@dataclass(frozen=True)
class ContractFrame:
    title: str
    first_party: str
    second_party: str
    first_sign: str
    second_sign: str
    #: Только договор поставки ссылается на «Основание: КП №»; у остальных его нет, пока нет КП.
    supply: bool


def supply_frame(title: str = "") -> ContractFrame:
    return ContractFrame(
        title=title or _("Договор поставки"),
        first_party=_("Поставщик"),
        second_party=_("Покупатель"),
        first_sign=_("От Поставщика:"),
        second_sign=_("От Покупателя:"),
        supply=True,
    )


def frame_of(template) -> ContractFrame:
    """Рамка по шаблону: `None` — договор поставки по умолчанию."""
    if template is None:
        return supply_frame()
    name = (getattr(template, "name", "") or "").strip()
    if getattr(template, "subject", "") == SUPPLY and not getattr(template, "base_role", ""):
        return supply_frame(name)
    kind = getattr(template, "counterparty_kind", "")
    if kind == "partner":
        second, second_sign = _("Партнёр"), _("От Партнёра:")
    elif kind == "client":
        second, second_sign = _("Клиент"), _("От Клиента:")
    else:
        return ContractFrame(
            title=name or _("Договор"),
            first_party=_("Сторона 1"),
            second_party=_("Сторона 2"),
            first_sign=_("От Стороны 1:"),
            second_sign=_("От Стороны 2:"),
            supply=False,
        )
    return ContractFrame(
        title=name or _("Договор"),
        first_party=_("Компания"),
        second_party=second,
        first_sign=_("От Компании:"),
        second_sign=second_sign,
        supply=False,
    )
