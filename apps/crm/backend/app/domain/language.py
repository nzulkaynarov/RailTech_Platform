"""Определение языка сообщения: ru / uz / en (CLAUDE.md §11, SPEC §7.1).

Эвристика: алфавит → кириллица (ru/uz по ўқғҳ) или латиница (uz/en по
оценке узбекских признаков против английских служебных слов). Используется
для выбора конфигурации полнотекстового поиска и как начальная гипотеза языка
диалога (язык фиксирует агент, SPEC §7.1).
"""

import re
from typing import Final, Literal

from app.domain.text import normalize_question

Language = Literal["ru", "uz", "en"]

DEFAULT_LANGUAGE: Final[Language] = "ru"

_CYRILLIC = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)
_UZ_CYRILLIC = re.compile(r"[ўқғҳ]", re.IGNORECASE)
_CYR_WORDS = re.compile(r"[а-яёўқғҳ]+", re.IGNORECASE)
# Узбекская кириллица без ўқғҳ (пишут с русской раскладки): частые слова, которых нет в русском.
_UZ_CYR_WORDS: Final = frozenset(
    "нима қандай кандай керак бор борми йўқ йук йок ассалому алейкум алайкум рахмат "
    "раҳмат қанча канча нархи нарх салом илтимос учун билан ва хизмат мен сиз биз бу "
    "қачон качон қаерда каерда қилиш килиш мумкин мумкинми яхши хоп хўп".split()
)
_RU_WORDS: Final = frozenset(
    "и в во не на что как я вы мы это есть нет да можно сколько цена здравствуйте "
    "привет у с по для мне нам вас какой какая где когда".split()
)
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
        return "uz" if _UZ_CYRILLIC.search(text) or _uzbek_cyrillic(text) else "ru"
    return "uz" if _uzbek_score(text) > _english_score(text) else "en"


def _uzbek_cyrillic(text: str) -> bool:
    words = [w.casefold() for w in _CYR_WORDS.findall(text)]
    uz = sum(1 for w in words if w in _UZ_CYR_WORDS)
    return uz > 0 and uz >= sum(1 for w in words if w in _RU_WORDS)


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


def next_language(
    current: Language, confirmed: bool, candidate: Language | None, detected: Language
) -> tuple[Language, bool, Language | None]:
    """Язык ответа и состояние фиксации (SPEC §7.1).

    Язык фиксируется после двух подряд сообщений на одном языке; зафиксированный
    язык меняет только команда /lang. Возвращает (язык, зафиксирован, кандидат).
    """
    if confirmed:
        return current, True, None
    if candidate == detected:
        return detected, True, None
    return detected, False, detected


# Явная просьба сменить язык (Q-022). Фразы — в виде normalize_question (дефис → пробел,
# апострофы → «'»). Только короткие сообщения: «как будет X in English» — не просьба.
_SWITCH: Final[dict[Language, tuple[str, ...]]] = {
    "ru": (
        "на русском",
        "по русски",
        "на русский",
        "русский язык",
        "russian please",
        "in russian",
        "ruscha",
        "rus tilida",
    ),
    "uz": (
        "o'zbekcha",
        "ozbekcha",
        "uzbekcha",
        "o'zbek tilida",
        "ozbek tilida",
        "uzbek tilida",
        "ўзбекча",
        "узбекча",
        "ўзбек тилида",
        "узбек тилида",
        "на узбекском",
        "по узбекски",
        "in uzbek",
        "uzbek please",
    ),
    "en": (
        "in english",
        "english please",
        "speak english",
        "на английском",
        "по английски",
        "inglizcha",
        "ingliz tilida",
    ),
}
_SWITCH_MAX_WORDS: Final = 5


def requested_language(text: str) -> Language | None:
    """Язык, на который человек явно просит перейти («давай по-русски», «in English»)."""
    normalized = normalize_question(text)
    if not normalized or len(normalized.split()) > _SWITCH_MAX_WORDS:
        return None
    haystack = f" {normalized} "
    for language, phrases in _SWITCH.items():
        if any(f" {phrase} " in haystack for phrase in phrases):
            return language
    return None


def mismatch_offer(
    fixed: Language, detected: Language, streak: int, offered: bool
) -> tuple[int, bool]:
    """Язык зафиксирован, а человек пишет на другом: (новая серия, предложить кнопки?).

    Кнопки языка предлагаются один раз — после двух сообщений подряд не на языке диалога.
    """
    if detected == fixed:
        return 0, False
    streak += 1
    return streak, streak >= 2 and not offered
