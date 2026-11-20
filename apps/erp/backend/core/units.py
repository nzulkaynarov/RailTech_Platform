"""Единица, написанная текстом («т», «ШТ.», «тонн», «м2»), → единица справочника (ADR-0027 п. 10, СЦ-10).

Детерминированно, без ИИ: код и три названия справочника без учёта регистра, «ё», пробелов и точек (NFKC: «м²» = «м2»),
затем короткий список частых написаний. Не узнали или узнали неоднозначно — None: текст остаётся как написан.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional

_NOISE = re.compile(r"[\s.]+")

#: Частые написания вне названий справочника; ключи — уже `unit_key`, коды — `core/seeds/uom.py`.
SYNONYMS: dict[str, str] = {
    "штук": "H87",
    "штука": "H87",
    "pcs": "H87",
    "pc": "H87",
    "комплект": "SET",
    "к-т": "SET",
    "тонна": "TNE",
    "тонн": "TNE",
    "тн": "TNE",
    "метр": "MTR",
    "пм": "MTR",
    "погм": "MTR",
    "квм": "MTK",
    "кубм": "MTQ",
    "килограмм": "KGM",
    "упаковка": "XPK",
    "уп": "XPK",
    "ч": "HUR",
    "сут": "DAY",
}

UnitMatch = Callable[[Optional[str]], Optional[tuple[str, str]]]


def unit_key(text) -> str:
    return _NOISE.sub("", unicodedata.normalize("NFKC", str(text or "")).casefold().replace("ё", "е"))


def unit_resolver(*, code_max: int = 8, label_max: int = 32) -> UnitMatch:
    """«текст → (код, подпись справочника)» или None. Справочник читается один раз — при первом непустом тексте."""
    index: Optional[dict[str, set[str]]] = None
    names: dict[str, str] = {}

    def _load() -> dict[str, set[str]]:
        from core.models import UnitOfMeasure

        labels: dict[str, set[str]] = {}
        for unit in UnitOfMeasure.objects.filter(is_active=True).only("code", "name", "name_uz", "name_en"):
            if len(unit.code) > code_max:  # QuoteItem.unit_code — 8 знаков
                continue
            names[unit.code] = unit.name
            for label in (unit.code, unit.name, unit.name_uz, unit.name_en):
                key = unit_key(label)
                if key:
                    labels.setdefault(key, set()).add(unit.code)
        return labels

    def resolve(text):
        nonlocal index
        key = unit_key(text)
        if not key:
            return None
        if index is None:
            index = _load()
        codes = index.get(key)
        if codes is None and SYNONYMS.get(key) in names:
            codes = {SYNONYMS[key]}
        if not codes or len(codes) != 1:  # неоднозначно — не угадываем
            return None
        code = next(iter(codes))
        return code, names[code][:label_max]

    return resolve
