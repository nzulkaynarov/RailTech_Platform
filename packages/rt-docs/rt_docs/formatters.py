"""Форматтеры по языку документа: даты, числа, суммы, валюта, сумма прописью (ru, uz-латиница, en).

Русская и английская пропись — перенос `apps/erp/backend/crm/services/money_words.py` (тот же формат:
«Двадцать миллионов шестьсот восемь тысяч сум 00 тийин»), узбекская (латиница, ʻ = U+02BB) — новая:
«Bir million ikki yuz ming soʻm 00 tiyin».
Пропись — денежный реквизит, поэтому таблицы выписаны явно; неизвестная валюта словом не называется (код ISO и /100).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .model import Lang, Money, Value

NBSP = " "

_MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_MONTHS_UZ = (
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
)
_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_date(value: date, lang: Lang, *, long: bool = True) -> str:
    """ru «28 октября 2026 г.», uz «2026-yil 28-oktabr», en «28 October 2026»; long=False — «28.10.2026»."""
    if not long:
        return value.strftime("%d.%m.%Y")
    if lang == "ru":
        return f"{value.day}{NBSP}{_MONTHS_RU[value.month - 1]} {value.year}{NBSP}г."
    if lang == "uz":
        return f"{value.year}-yil {value.day}-{_MONTHS_UZ[value.month - 1]}"
    return f"{value.day} {_MONTHS_EN[value.month - 1]} {value.year}"


def format_number(value: Decimal | int, lang: Lang, *, decimals: int = 2) -> str:
    """ru и uz: «1 234 567,89» (неразрывный пробел, запятая); en: «1,234,567.89»."""
    quant = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    amount = Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    text = f"{amount:,.{decimals}f}"  # 1,234,567.89
    if lang == "en":
        return text
    return text.replace(",", NBSP).replace(".", ",")


_CURRENCY_NAMES: dict[str, dict[Lang, str]] = {
    "UZS": {"ru": "сум", "uz": "soʻm", "en": "UZS"},
}


def currency_label(currency: str, lang: Lang) -> str:
    """Название валюты после суммы: UZS — «сум» / «soʻm»; прочие — код ISO (USD, EUR, RUB)."""
    code = currency.upper()
    return _CURRENCY_NAMES.get(code, {}).get(lang, code)


def format_money(value: Money, lang: Lang) -> str:
    """«1 234 567,89 сум» / «1 234 567,89 soʻm» / «1,234,567.89 UZS»."""
    return f"{format_number(value.amount, lang)}{NBSP}{currency_label(value.currency, lang)}"


def format_value(value: Value, lang: Lang) -> str:
    """Значение переменной для печати по языку документа."""
    if isinstance(value, Money):
        return format_money(value, lang)
    if isinstance(value, date):
        return format_date(value, lang)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | Decimal):
        return format_number(value, lang, decimals=0 if isinstance(value, int) else 2)
    return value


# ─── сумма прописью: общее ──────────────────────────────────────────────────────────────────────


def _split(value: Decimal | int | str | None) -> tuple[bool, int, int] | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    negative = amount < 0
    try:
        amount = abs(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:  # больше точности контекста Decimal — словом не печатается
        return None
    integer = int(amount)
    return negative, integer, int((amount - integer) * 100)


def _groups(number: int) -> list[int]:
    groups: list[int] = []
    while number:
        number, group = divmod(number, 1000)
        groups.append(group)
    return groups


def _capitalize(words: list[str]) -> str:
    phrase = " ".join(w for w in words if w)
    return phrase[:1].upper() + phrase[1:]


def amount_in_words(value: Decimal | int | str | None, currency: str, lang: Lang) -> str:
    """Сумма прописью на языке документа; None или мусор — «—»."""
    if lang == "ru":
        return _ru(value, currency)
    if lang == "uz":
        return _uz(value, currency)
    return _en(value, currency)


# ─── русский ──────────────────────────────────────────────────────────────────────────────────

_RU_ONES_M = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
_RU_ONES_F = ("", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
_RU_TEENS = (
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_RU_TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто")
_RU_HUNDREDS = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот")
_RU_SCALES: tuple[tuple[str, str, str, str], ...] = (
    ("", "", "", "m"),
    ("тысяча", "тысячи", "тысяч", "f"),
    ("миллион", "миллиона", "миллионов", "m"),
    ("миллиард", "миллиарда", "миллиардов", "m"),
    ("триллион", "триллиона", "триллионов", "m"),
)
#: Валюта: (основная одна/две/пять, род), (дробная одна/две/пять). UZS «сум»/«тийин» не склоняются (как в ERP).
_RU_CURRENCIES: dict[str, tuple[tuple[str, str, str, str], tuple[str, str, str]]] = {
    "UZS": (("сум", "сум", "сум", "m"), ("тийин", "тийин", "тийин")),
    "RUB": (("рубль", "рубля", "рублей", "m"), ("копейка", "копейки", "копеек")),
    "USD": (("доллар", "доллара", "долларов", "m"), ("цент", "цента", "центов")),
    "EUR": (("евро", "евро", "евро", "m"), ("цент", "цента", "центов")),
    "KZT": (("тенге", "тенге", "тенге", "m"), ("тиын", "тиын", "тиын")),
}


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def _ru_group(group: int, gender: str) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(group, 100)
    if hundreds:
        words.append(_RU_HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(_RU_TEENS[rest - 10])
    else:
        tens, ones = divmod(rest, 10)
        if tens:
            words.append(_RU_TENS[tens])
        if ones:
            words.append((_RU_ONES_F if gender == "f" else _RU_ONES_M)[ones])
    return words


def _ru(value: Decimal | int | str | None, currency: str) -> str:
    parts = _split(value)
    if parts is None:
        return "—"
    negative, integer, sub = parts
    if integer >= 10 ** (3 * len(_RU_SCALES)):
        return "—"
    known = _RU_CURRENCIES.get(currency.upper())
    base_gender = known[0][3] if known else "m"
    groups = _groups(integer)
    words: list[str] = []
    for index in range(len(groups) - 1, 0, -1):
        if groups[index]:
            one, few, many, gender = _RU_SCALES[index]
            words += [*_ru_group(groups[index], gender), _ru_plural(groups[index], one, few, many)]
    if integer == 0:
        words.append("ноль")
    elif groups[0]:
        words += _ru_group(groups[0], base_gender)
    if known:
        (m1, m2, m5, _), (s1, s2, s5) = known
        words.append(_ru_plural(integer, m1, m2, m5))
        tail = f"{sub:02d} {_ru_plural(sub, s1, s2, s5)}"
    else:
        tail = f"{currency.upper()} {sub:02d}/100"
    phrase = _capitalize(words)
    return f"{'минус ' if negative else ''}{phrase} {tail}"


# ─── узбекский (латиница) ─────────────────────────────────────────────────────────────────────

_UZ_ONES = ("", "bir", "ikki", "uch", "toʻrt", "besh", "olti", "yetti", "sakkiz", "toʻqqiz")
_UZ_TENS = ("", "oʻn", "yigirma", "oʻttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "toʻqson")
_UZ_SCALES = ("", "ming", "million", "milliard", "trillion")
#: Валюта: (основная, дробная). Существительное после числительного в узбекском не изменяется.
_UZ_CURRENCIES = {
    "UZS": ("soʻm", "tiyin"),
    "RUB": ("rubl", "kopeyka"),
    "USD": ("AQSH dollari", "sent"),
    "EUR": ("yevro", "sent"),
    "KZT": ("tenge", "tiyin"),
}


def _uz_group(group: int) -> list[str]:
    """0 … 999: «bir yuz yigirma besh» (в денежных документах сотня — «bir yuz», как «bir ming»)."""
    words: list[str] = []
    hundreds, rest = divmod(group, 100)
    if hundreds:
        words += [_UZ_ONES[hundreds], "yuz"]
    tens, ones = divmod(rest, 10)
    if tens:
        words.append(_UZ_TENS[tens])
    if ones:
        words.append(_UZ_ONES[ones])
    return words


def _uz(value: Decimal | int | str | None, currency: str) -> str:
    parts = _split(value)
    if parts is None:
        return "—"
    negative, integer, sub = parts
    if integer >= 10 ** (3 * len(_UZ_SCALES)):
        return "—"
    groups = _groups(integer)
    words: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        if groups[index]:
            words += _uz_group(groups[index])
            if index:
                words.append(_UZ_SCALES[index])
    if integer == 0:
        words.append("nol")
    known = _UZ_CURRENCIES.get(currency.upper())
    if known:
        words.append(known[0])
        tail = f"{sub:02d} {known[1]}"
    else:
        tail = f"{currency.upper()} {sub:02d}/100"
    return f"{'minus ' if negative else ''}{_capitalize(words)} {tail}"


# ─── английский ───────────────────────────────────────────────────────────────────────────────

_EN_ONES = (
    "",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_EN_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_EN_SCALES = ("", "thousand", "million", "billion", "trillion")
_EN_CURRENCIES = {
    "UZS": ("soum", "soums", "tiyin", "tiyin"),
    "RUB": ("ruble", "rubles", "kopeck", "kopecks"),
    "USD": ("dollar", "dollars", "cent", "cents"),
    "EUR": ("euro", "euros", "cent", "cents"),
    "KZT": ("tenge", "tenge", "tiyn", "tiyn"),
}


def _en_group(group: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(group, 100)
    if hundreds:
        words += [_EN_ONES[hundreds], "hundred"]
    if rest:
        if rest < 20:
            words.append(_EN_ONES[rest])
        else:
            tens, ones = divmod(rest, 10)
            words.append(f"{_EN_TENS[tens]}-{_EN_ONES[ones]}" if ones else _EN_TENS[tens])
    return words


def _en(value: Decimal | int | str | None, currency: str) -> str:
    parts = _split(value)
    if parts is None:
        return "—"
    negative, integer, sub = parts
    if integer >= 10 ** (3 * len(_EN_SCALES)):
        return "—"
    groups = _groups(integer)
    words: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        if groups[index]:
            words += _en_group(groups[index])
            if index:
                words.append(_EN_SCALES[index])
    if integer == 0:
        words.append("zero")
    known = _EN_CURRENCIES.get(currency.upper())
    if known:
        words.append(known[0] if integer == 1 else known[1])
        tail = f"{sub:02d} {known[2] if sub == 1 else known[3]}"
    else:
        tail = f"{currency.upper()} {sub:02d}/100"
    return f"{'minus ' if negative else ''}{_capitalize(words)} {tail}"
