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


def code_tokens(key: str) -> set[str]:
    """Слова ключа с цифрами: «р65», «25», «1/11»."""
    return {word for word in key.split() if any(ch.isdigit() for ch in word)}


def _family(token: str) -> str:
    """Буквы до первой цифры: «р65» → «р», «м22» → «м», «25» → «» (у чистого числа семьи нет)."""
    match = re.match(r"\D*", token)
    return match.group(0) if match else ""


def codes_conflict(line_codes: set[str], card_key: str) -> bool:
    """У карточки другой код той же семьи («р50» против «р65»), а кода строки нет — это другая позиция."""
    card_words = set(card_key.split())
    card_codes = code_tokens(card_key)
    for token in line_codes:
        family = _family(token)
        if not family or token in card_words:
            continue
        if any(_family(word) == family and word != token for word in card_codes):
            return True
    return False
