"""Названия стран на русском, узбекском (латиница) и английском из Unicode CLDR через Babel (план справочников, PR 6).

Коды стран у нас свои (alpha-2, alpha-3, цифровой — `core/seeds/countries.py`), из библиотеки берутся только названия.
Узбекский апостроф приводится к принятому в проекте «‘» (U+2018): CLDR пишет то «ʻ», то «‘».
"""

from collections.abc import Iterable
from typing import Any

from babel import Locale

LANGS = {"ru": "name", "uz": "name_uz", "en": "name_en"}
_UZ_APOSTROPHES = str.maketrans({"ʻ": "‘"})


def babel_names(code: str) -> dict[str, str]:
    """Названия по alpha-2 на трёх языках; для кода, которого нет в CLDR, — пустые строки."""
    names = {}
    for lang in LANGS:
        name = Locale.parse(lang).territories.get(code.upper(), "")
        names[lang] = name.translate(_UZ_APOSTROPHES) if lang == "uz" else name
    return names


def fill_missing_names(country: Any) -> list[str]:
    """Пустые названия страны — из CLDR; заполненные (в том числе руками) не трогаются. Возвращает изменённые поля."""
    changed = []
    for lang, value in babel_names(country.code).items():
        field = LANGS[lang]
        if value and not getattr(country, field):
            setattr(country, field, value)
            changed.append(field)
    return changed


def fill_all(countries: Iterable[Any]) -> int:
    """Заполнить пустые названия у набора стран; возвращает число изменённых строк."""
    count = 0
    for country in countries:
        changed = fill_missing_names(country)
        if changed:
            country.save(update_fields=changed)
            count += 1
    return count
