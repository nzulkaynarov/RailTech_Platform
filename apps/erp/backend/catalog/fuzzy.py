"""Поиск товара по названию с опечатками на трёх языках (FR-26, стратегия 2026-11-12 «готовые решения»).

Средства PostgreSQL: `pg_trgm` (`word_similarity` — запрос как часть длинного названия). Запрос пробуется как набран и в
другой письменности: кириллица ↔ латиница (русская и узбекская транслитерация), поэтому «strelochniy» находит
«Стрелочный перевод», а «g'ildirak» — «Гилдирак» и «Gʻildirak». Порог отсекает случайные совпадения; лучшие — первыми.
"""

from __future__ import annotations

import re

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import FloatField, QuerySet
from django.db.models.functions import Greatest

#: Ниже — случайное сходство коротких слов; проверено на «стрелчный», «strelochniy», «bolt m12»
MIN_SCORE = 0.35
#: Транслитерация латиница → кириллица: сначала длинные сочетания (узбекская латиница и русская практическая)
_LAT_TO_CYR: tuple[tuple[str, str], ...] = (
    ("shch", "щ"),
    ("o'", "ў"),
    ("oʻ", "ў"),
    ("o‘", "ў"),
    ("g'", "ғ"),
    ("gʻ", "ғ"),
    ("g‘", "ғ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ts", "ц"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
    ("a", "а"),
    ("b", "б"),
    ("c", "к"),
    ("d", "д"),
    ("e", "е"),
    ("f", "ф"),
    ("g", "г"),
    ("h", "х"),
    ("i", "и"),
    ("j", "ж"),
    ("k", "к"),
    ("l", "л"),
    ("m", "м"),
    ("n", "н"),
    ("o", "о"),
    ("p", "п"),
    ("q", "қ"),
    ("r", "р"),
    ("s", "с"),
    ("t", "т"),
    ("u", "у"),
    ("v", "в"),
    ("w", "в"),
    ("x", "х"),
    ("y", "й"),
    ("z", "з"),
)
_CYR_TO_LAT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": "g'",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "қ": "q",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ў": "o'",
    "ф": "f",
    "х": "x",
    "ҳ": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
_LATIN = re.compile(r"[a-z]")
_CYRILLIC = re.compile(r"[а-яёўқғҳ]")


def to_cyrillic(text: str) -> str:
    out, i, low = [], 0, text.lower()
    while i < len(low):
        for latin, cyr in _LAT_TO_CYR:
            if low.startswith(latin, i):
                out.append(cyr)
                i += len(latin)
                break
        else:
            out.append(low[i])
            i += 1
    return "".join(out)


def to_latin(text: str) -> str:
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in text.lower())


def variants(query: str) -> list[str]:
    """Запрос как набран и в другой письменности — без повторов, в нижнем регистре."""
    base = " ".join(query.lower().split())
    found = [base]
    if _LATIN.search(base):
        found.append(to_cyrillic(base))
    if _CYRILLIC.search(base):
        found.append(to_latin(base))
    return list(dict.fromkeys(v for v in found if v))


def fuzzy_products(qs: QuerySet, query: str, *, limit: int) -> list:
    """Товары, похожие названием на запрос в любой из письменностей, лучшие первыми; порог — `MIN_SCORE`."""
    options = variants(query)
    if not options or len(options[0]) < 3:
        return []
    scores = [TrigramWordSimilarity(v, "name") for v in options]
    score = Greatest(*scores, output_field=FloatField()) if len(scores) > 1 else scores[0]
    return list(
        qs.annotate(fuzzy_score=score).filter(fuzzy_score__gte=MIN_SCORE).order_by("-fuzzy_score", "name")[:limit]
    )
