"""Определение языка сообщения: ru / uz / en (CLAUDE.md §11, SPEC §7.1).

Эвристика: алфавит → кириллица (ru/uz по ўқғҳ) или латиница (uz/en по
оценке узбекских признаков против английских служебных слов). Используется
для выбора конфигурации полнотекстового поиска и как начальная гипотеза языка
диалога (язык фиксирует агент, SPEC §7.1).
"""

import re
from typing import Final, Literal

Language = Literal["ru", "uz", "en"]

DEFAULT_LANGUAGE: Final[Language] = "ru"

_CYRILLIC = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)
_UZ_CYRILLIC = re.compile(r"[ўқғҳ]", re.IGNORECASE)
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)
_WORDS = re.compile(r"[a-z‘’'`ʻʼ]+", re.IGNORECASE)

_UZ_APOSTROPHE = re.compile(r"[og][‘’'`ʻʼ]", re.IGNORECASE)
_UZ_WORDS: Final = frozenset(
    "va uchun bilan qanday qancha nima necha kerak bormi narxi salom rahmat iltimos "
    "bu men siz biz ular yoq yo'q ha xizmat qayerda qachon nega ham emas bor".split()
)
_UZ_SUFFIXES: Final = (
    "larni",
    "lar",
    "ning",
    "dagi",
    "dan",
    "ga",
    "ni",
    "mi",
    "moq",
    "ish",
    "siz",
    "miz",
)
_EN_WORDS: Final = frozenset(
    "the a an and or is are was were what how why when where who do does can could "
    "you your i we it this that to of in on for with price cost please hello hi".split()
)


def detect_language(text: str, default: Language = DEFAULT_LANGUAGE) -> Language:
    """Язык текста; при недостатке сигнала — `default`."""
    cyrillic = len(_CYRILLIC.findall(text))
    latin = len(_LATIN.findall(text))
    if cyrillic == 0 and latin == 0:
        return default
    if cyrillic >= latin:
        return "uz" if _UZ_CYRILLIC.search(text) else "ru"
    return "uz" if _uzbek_score(text) > _english_score(text) else "en"


def _uzbek_score(text: str) -> float:
    words = [w.casefold() for w in _WORDS.findall(text)]
    score = 2.0 * len(_UZ_APOSTROPHE.findall(text))
    for word in words:
        if word in _UZ_WORDS:
            score += 2
        elif len(word) > 4 and word.endswith(_UZ_SUFFIXES):
            score += 1
        if re.search(r"q(?!u)", word):
            score += 1
    return score


def _english_score(text: str) -> float:
    return 2.0 * sum(1 for w in _WORDS.findall(text) if w.casefold() in _EN_WORDS)
