"""Unit tests for the document money/qty formatting filters and «сумма прописью» converter
(crm/templatetags/document_format.py + crm/services/money_words.py). Boundaries: zero, kopecks,
billions, negative (discount) amounts, integer vs fractional quantities."""

from decimal import Decimal

from crm.services.money_words import money_in_words
from crm.templatetags.document_format import money, money_words, qty

NBSP = " "


# ── money ────────────────────────────────────────────────────────────
def test_money_groups_thousands_with_nbsp_and_comma_decimal():
    assert money(Decimal("20608000.00")) == f"20{NBSP}608{NBSP}000,00"


def test_money_appends_currency_code():
    assert money(Decimal("20608000"), "UZS") == f"20{NBSP}608{NBSP}000,00{NBSP}UZS"


def test_money_small_value_has_no_separator():
    assert money(Decimal("200.05")) == "200,05"
    assert money(Decimal("550.05")) == "550,05"


def test_money_keeps_kopecks_exact():
    assert money(Decimal("2888861.09"), "UZS") == f"2{NBSP}888{NBSP}861,09{NBSP}UZS"


def test_money_zero_and_none():
    assert money(Decimal("0")) == "0,00"
    assert money(None) == "—"
    assert money("") == "—"


def test_money_negative_keeps_sign():
    assert money(Decimal("-1500.50")) == "-1{NBSP}500,50".replace("{NBSP}", NBSP)


def test_money_accepts_float_and_int_and_str():
    assert money(1000) == f"1{NBSP}000,00"
    assert money("1234.5") == f"1{NBSP}234,50"


def test_money_billions():
    assert money(Decimal("1234567890.12")) == f"1{NBSP}234{NBSP}567{NBSP}890,12"


# ── money_words / money_in_words ─────────────────────────────────────
def test_money_words_matches_spec_example():
    assert money_in_words(Decimal("20608000.00"), "UZS") == "Двадцать миллионов шестьсот восемь тысяч сум 00 тийин"


def test_money_words_one_uses_masculine_and_singular():
    assert money_in_words(Decimal("1.00"), "UZS") == "Один сум 00 тийин"


def test_money_words_kopecks_subunit():
    assert money_in_words(Decimal("21.45"), "RUB") == "Двадцать один рубль 45 копеек"


def test_money_words_rub_plural_forms():
    assert money_in_words(Decimal("2.00"), "RUB") == "Два рубля 00 копеек"
    assert money_in_words(Decimal("5.00"), "RUB") == "Пять рублей 00 копеек"


def test_money_words_thousands_feminine():
    assert money_in_words(Decimal("2000.00"), "UZS") == "Две тысячи сум 00 тийин"


def test_money_words_zero():
    assert money_in_words(Decimal("0.00"), "UZS") == "Ноль сум 00 тийин"


def test_money_words_negative_prefix():
    assert money_in_words(Decimal("-100.00"), "UZS").startswith("минус ")


def test_money_words_none_returns_dash():
    assert money_in_words(None) == "—"


def test_money_words_filter_delegates():
    assert money_words(Decimal("1.00"), "UZS") == "Один сум 00 тийин"


# ── qty ──────────────────────────────────────────────────────────────
def test_qty_integer_has_no_decimals():
    assert qty(Decimal("10"), "шт.") == f"10{NBSP}шт."


def test_qty_fractional_keeps_decimals():
    assert qty(Decimal("2.5"), "т") == f"2.5{NBSP}т"


def test_qty_without_unit():
    assert qty(Decimal("7")) == "7"


def test_qty_none_returns_dash():
    assert qty(None, "шт.") == f"—{NBSP}шт."
