"""Ключ имени позиции каталога (СЦ-10): поиск той же позиции, записанной иначе.

Не различает регистр, «ё», латинские двойники кириллицы (P/Р, M/М, x/х), пунктуацию и пробелы; РАЗЛИЧАЕТ состав и
порядок слов, дефис и дробную часть числа — похожие имена («Болт М22» и «Болт М24») не склеиваются.
"""

import re
import unicodedata

_HOMOGLYPHS = str.maketrans("abcehkmoptxy", "авсенкмортху")  # после casefold; одинаково для обеих сторон
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_SEPARATORS = re.compile(r"(?:(?<!\d)[.,]|[.,](?!\d)|[\s;:!?\"'«»„“”()\[\]{}])+")

MAX_LENGTH = 255


def name_key(text) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold().replace("ё", "е").translate(_HOMOGLYPHS)
    text = _DECIMAL_COMMA.sub(".", text)
    return " ".join(_SEPARATORS.sub(" ", text).split())[:MAX_LENGTH]
