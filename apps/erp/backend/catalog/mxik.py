"""МХИК (ИКПУ) — классификатор товаров Налогового комитета (план 1.8; исследование 2026-11-11-reference-data §B3).

Поиск по слову — открытый адрес tasnif.soliq.uz без ключа (`/api/cls-api/mxik/search/by-params`). Документации и условий
у адреса нет, поэтому классификатор — подсказка: недоступен — `MxikUnavailable`, и код вводится вручную. Хранится у
товара только выбранное: код, название, единица и упаковка.

Классификатор внешний, своей копии справочника у нас нет (индекс pg_trgm строить не на чем), поэтому релевантность — наша:
адрес отдаёт широкую выдачу (в прогоне «накладка» давала перевозку пассажиров и газоснабжение), а здесь она разбирается по
основам слов и пересортируется: слово в названии позиции выше слова в пути групп, точное слово выше начала слова, код
товара (глубокий) выше узла группы; совпадение только в родительских группах отбрасывается. Тексты сравниваются в одном
написании: кириллица, новая и старая латиница узбекского приводятся к одной латинской основе.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

SEARCH_PATH = "/api/cls-api/mxik/search/by-params"
MAX_RESULTS = 10
#: Сколько позиций просим у классификатора: из широкой выдачи берём лучшие `MAX_RESULTS`.
FETCH_SIZE = 60
CODE_LENGTH = 17


class MxikUnavailable(Exception):
    """Классификатор не ответил или ответил не так: код вводится вручную."""


def normalize_code(value: Any) -> str:
    """Код МХИК — ровно 17 цифр; пусто — снять код. Иначе ``ValueError``."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not (text.isdigit() and len(text) == CODE_LENGTH):
        raise ValueError("mxik code must be 17 digits")
    return text


def _row(raw: dict[str, Any]) -> dict[str, Any] | None:
    code = str(raw.get("mxikCode") or "").strip()
    if not (code.isdigit() and len(code) == CODE_LENGTH):
        return None
    packages = [p for p in raw.get("packages") or [] if isinstance(p, dict)]
    package = packages[0] if packages else {}
    return {
        "code": code,
        "name": str(raw.get("mxikName") or raw.get("subPositionName") or raw.get("positionName") or "")[:500],
        "group": str(raw.get("groupName") or raw.get("className") or "")[:300],
        "path": _path(raw),
        "unit": str(raw.get("unitName") or package.get("unitName") or "")[:100],
        "package": str(package.get("nameRu") or package.get("name") or "")[:200],
    }


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
    "ö": "o", "ğ": "g", "ş": "sh", "ç": "ch",
}  # fmt: skip
_APOSTROPHES = "'`ʻʼ‘’´"
_WORD = re.compile(r"[a-z0-9]+")
#: Окончания русских и узбекских слов; длинные раньше коротких. Основа остаётся не короче 4 знаков.
_SUFFIXES = tuple(
    sorted(
        (
            "ami", "ymi", "ogo", "ego", "yya", "ning", "lar", "dan", "yy", "ov", "ev", "ey", "oy", "om", "em", "ym", "im",
            "ah", "am", "ya", "yu", "ye", "ia", "ii", "ie", "ni", "ga", "da", "a", "y", "i", "e", "o", "u", "s",
        ),
        key=len,
        reverse=True,
    )
)  # fmt: skip
MIN_STEM = 4


def fold(text: str) -> str:
    """Одно написание: нижний регистр, кириллица и узбекские знаки (Oʻ Gʻ, Ö Ğ Ş Ç) — в латинский «скелет»."""
    lowered = (text or "").lower()
    for mark in _APOSTROPHES:
        lowered = lowered.replace(mark, "")
    return "".join(_TRANSLIT.get(ch, ch) for ch in lowered)


def stem(word: str) -> str:
    """Основа слова: срезаем одно окончание, пока остаётся не меньше `MIN_STEM` знаков."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            return word[: -len(suffix)]
    return word


def stems(text: str) -> list[str]:
    return [stem(word) for word in _WORD.findall(fold(text))]


def depth(code: str) -> int:
    """Глубина кода: 1 — группа (3 знака), 2 — класс (5), 3 — позиция (8), 4 — подпозиция (11), 5 — товар (17)."""
    significant = len(code.rstrip("0"))
    for level, limit in enumerate((3, 5, 8, 11), start=1):
        if significant <= limit:
            return level
    return 5


def _match(token: str, words: list[str]) -> int:
    """3 — слово совпало по основе, 2 — слово начинается с написанного, 0 — нет."""
    if token in words:
        return 3
    if any(word.startswith(token) for word in words):
        return 2
    return 0


def _rank(query_stems: list[str], raw: dict[str, Any], row: dict[str, Any]) -> tuple[float, int] | None:
    """`(релевантность, глубина)` или `None`, если слово есть только в родительских группах либо нигде.

    Название позиции — своё имя (`mxikName`, `subPositionName`, `positionName`); путь — группа и класс над ней.
    Каждое слово запроса должно найтись в названии или в пути, и хотя бы одно — в названии.
    """
    own = stems(" ".join(str(raw.get(key) or "") for key in ("mxikName", "subPositionName", "positionName")))
    path = stems(" ".join(str(raw.get(key) or "") for key in ("groupName", "className")))
    score = 0.0
    in_name = False
    for token in query_stems:
        hit = _match(token, own)
        if hit:
            in_name = True
            score += hit
        elif _match(token, path):
            score += 0.5
        else:
            return None
    if not in_name:
        return None
    return score, depth(row["code"])


def _path(raw: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("groupName", "className", "positionName", "subPositionName"):
        value = str(raw.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    name = str(raw.get("mxikName") or "").strip()
    if name in parts:
        parts.remove(name)
    return " › ".join(parts)[:500]


def search(text: str, *, lang: str = "ru") -> list[dict[str, Any]]:
    """До 10 лучших позиций классификатора по слову или коду. Недоступен — ``MxikUnavailable``."""
    query = (text or "").strip()
    if len(query) < 2:
        return []
    base = getattr(settings, "MXIK_BASE_URL", "https://tasnif.soliq.uz").rstrip("/")
    try:
        response = httpx.get(
            f"{base}{SEARCH_PATH}",
            params={
                "searchText": query[:100],
                "size": FETCH_SIZE,
                "page": 0,
                "lang": "uz_latn" if lang == "uz" else "ru",
            },
            timeout=getattr(settings, "MXIK_TIMEOUT_S", 8.0),
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("MXIK classifier unavailable: %s", exc.__class__.__name__)
        raise MxikUnavailable from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("content") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise MxikUnavailable
    pairs = [(raw, row) for raw in items if isinstance(raw, dict) for row in [_row(raw)] if row]
    if query.isdigit():  # поиск по коду: порядок и состав — как ответил классификатор
        return [row for _, row in pairs][:MAX_RESULTS]
    query_stems = stems(query)
    if not query_stems:
        return []
    ranked = []
    for index, (raw, row) in enumerate(pairs):
        rank = _rank(query_stems, raw, row)
        if rank is not None:
            ranked.append((-rank[0], -rank[1], index, row))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:MAX_RESULTS]]
