"""Вшитые шрифты документа: Noto Sans и Noto Serif 2.015 (SIL OFL 1.1, rt_docs/fonts/OFL.txt), подмножество
scripts/subset_fonts.py. Рендер видит только их (rt_docs.pdf — изолированный fontconfig), поэтому символ вне шрифта
печатается «тофу», а не молча другим шрифтом: `missing_glyphs` предупреждает об этом заранее.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from fontTools.ttLib import TTFont

from .css import FONT_FILES
from .fetcher import font_bytes

#: Символы, без которых документ на узбекском и русском не печатается (проверяет тест шрифтов).
REQUIRED_CHARS = "ʻʼ‘’ўқғҳЎҚҒҲ№«»—–…"


@lru_cache(maxsize=16)
def _cmap(name: str) -> frozenset[int]:
    font = TTFont(BytesIO(font_bytes(name)))
    return frozenset(font.getBestCmap())


def coverage(font: str) -> frozenset[int]:
    """Кодовые точки, которые есть во всех четырёх начертаниях семейства (`sans` или `serif`)."""
    sets = [_cmap(name) for name, _, _ in FONT_FILES[font]]
    common = sets[0]
    for other in sets[1:]:
        common &= other
    return common


def missing_glyphs(text: str, font: str = "sans") -> list[str]:
    """Символы текста, которых нет во вшитом семействе (пробельные и управляющие не считаются)."""
    have = coverage(font)
    return sorted({ch for ch in text if not ch.isspace() and ord(ch) >= 0x20 and ord(ch) not in have})
