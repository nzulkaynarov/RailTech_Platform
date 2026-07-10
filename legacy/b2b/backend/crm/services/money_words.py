"""«Сумма прописью» — amount-in-words for CIS commercial documents (КП / договор / инвойс / акт).

A self-contained Russian integer-to-words converter with per-currency word tables. Written in
house on purpose: `num2words` is not a dependency and adding it would require regenerating the
hashed requirements lock (INF-05). Rule 8 — the business logic lives here; the `money_words`
template filter (crm/templatetags/document_format.py) is a thin wrapper.

Format (de-facto invoice standard): «Двадцать миллионов шестьсот восемь тысяч сум 00 тийин».
The integer part is spelled out, the fractional subunit stays as two digits + its word.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Ones 1..9 — masculine and feminine (feminine only differs for 1 and 2: одна/две).
_ONES_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_ONES_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = [
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
]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = [
    "",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
]

# Scale groups above the base unit: (one, few, many, gender). Base unit gender comes from the currency.
_SCALES = [
    None,  # group 0 = base units, handled by currency words
    ("тысяча", "тысячи", "тысяч", "f"),
    ("миллион", "миллиона", "миллионов", "m"),
    ("миллиард", "миллиарда", "миллиардов", "m"),
    ("триллион", "триллиона", "триллионов", "m"),
    ("квадриллион", "квадриллиона", "квадриллионов", "m"),
    ("квинтиллион", "квинтиллиона", "квинтиллионов", "m"),
]
# Largest integer the scale table can spell (below 10^21). Beyond it we degrade gracefully instead
# of an IndexError that would crash the whole WeasyPrint render for one oversized cell.
_MAX_SPELLABLE = 10 ** (3 * (len(_SCALES) - 1) + 3)

# Currency words: (main one/few/many + gender, subunit one/few/many). UZS «сум»/«тийин» are invariable.
_CURRENCIES = {
    "UZS": (("сум", "сум", "сум", "m"), ("тийин", "тийин", "тийин")),
    "RUB": (("рубль", "рубля", "рублей", "m"), ("копейка", "копейки", "копеек")),
    "USD": (("доллар", "доллара", "долларов", "m"), ("цент", "цента", "центов")),
    "EUR": (("евро", "евро", "евро", "m"), ("цент", "цента", "центов")),
    "KZT": (("тенге", "тенге", "тенге", "m"), ("тиын", "тиын", "тиын")),
}
_DEFAULT_CURRENCY = _CURRENCIES["UZS"]


def _plural(amount, one, few, many):
    """Pick the Russian plural form for `amount` (…1 → one, …2-4 → few, else many; teens → many)."""
    tail = amount % 100
    if 11 <= tail <= 14:
        return many
    last = amount % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _group_to_words(group, gender):
    """Words for one 0..999 group, in the given grammatical gender ('m' | 'f')."""
    words = []
    hundreds, rest = divmod(group, 100)
    if hundreds:
        words.append(_HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
    else:
        tens, ones = divmod(rest, 10)
        if tens:
            words.append(_TENS[tens])
        if ones:
            words.append((_ONES_F if gender == "f" else _ONES_M)[ones])
    return words


def _integer_to_words(number):
    """Spell out a non-negative integer using the scale groups. Base group returned genderless
    (its gender is applied by the caller via the currency), higher groups carry their own gender."""
    if number == 0:
        return ["ноль"], 0
    groups = []
    remainder = number
    while remainder:
        remainder, group = divmod(remainder, 1000)
        groups.append(group)
    words = []
    base_group = groups[0]
    for index in range(len(groups) - 1, 0, -1):
        group = groups[index]
        if group == 0:
            continue
        one, few, many, gender = _SCALES[index]
        words.extend(_group_to_words(group, gender))
        words.append(_plural(group, one, few, many))
    return words, base_group


def money_in_words(value, currency_code="UZS"):
    """«Сумма прописью»: `«Двадцать миллионов … сум 00 тийин»`. Capitalized, subunit as 2 digits.

    Accepts Decimal / int / float / numeric str. None or unparseable → «—». Negative amounts
    (discount lines) are prefixed «минус». Currency word tables cover UZS/RUB/USD/EUR/KZT; an
    unknown code falls back to UZS words but keeps the given ISO code out of the phrase.
    """
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "—"

    negative = amount < 0
    amount = abs(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer_part = int(amount)
    subunit = int((amount - integer_part) * 100)

    if integer_part >= _MAX_SPELLABLE:
        # Absurdly large total — degrade gracefully instead of crashing the WeasyPrint render;
        # the numeric money cell still shows the value.
        return "—"

    known = _CURRENCIES.get((currency_code or "").upper())
    if known:
        (main_one, main_few, main_many, main_gender), (sub_one, sub_few, sub_many) = known
        words, base_group = _integer_to_words(integer_part)
        words.extend(_group_to_words(base_group, main_gender) if integer_part else [])
        words.append(_plural(integer_part, main_one, main_few, main_many))
        tail = f"{subunit:02d} {_plural(subunit, sub_one, sub_few, sub_many)}"
    else:
        # Unknown currency (e.g. CNY): NEVER claim «сум» — that would contradict the numeric total's
        # currency. Spell the number (masculine) and append the raw ISO code + subunit as digits.
        words, base_group = _integer_to_words(integer_part)
        words.extend(_group_to_words(base_group, "m") if integer_part else [])
        code = (currency_code or "").upper()
        tail = f"{code} {subunit:02d}/100".strip()

    phrase = " ".join(part for part in words if part)
    phrase = phrase[:1].upper() + phrase[1:]
    if negative:
        phrase = "минус " + phrase
    return f"{phrase} {tail}"
