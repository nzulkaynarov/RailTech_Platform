"""Форматтеры ru/uz/en: даты, числа, суммы, сумма прописью (ru — как ERP money_words, uz — латиница с ʻ)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rt_docs.formatters import NBSP, amount_in_words, format_date, format_money, format_number, format_value
from rt_docs.model import LANGS, Money

D = date(2026, 10, 28)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("ru", f"28{NBSP}октября 2026{NBSP}г."), ("uz", "2026-yil 28-oktabr"), ("en", "28 October 2026")],
)
def test_long_date_by_document_language(lang: str, expected: str) -> None:
    assert format_date(D, lang) == expected  # type: ignore[arg-type]


def test_short_date_is_the_same_in_every_language() -> None:
    assert {format_date(D, lang, long=False) for lang in LANGS} == {"28.10.2026"}


def test_numbers_and_money() -> None:
    assert format_number(Decimal("1234567.891"), "ru") == f"1{NBSP}234{NBSP}567,89"
    assert format_number(Decimal("1234567.891"), "uz") == f"1{NBSP}234{NBSP}567,89"
    assert format_number(Decimal("1234567.891"), "en") == "1,234,567.89"
    assert format_number(1500, "ru", decimals=0) == f"1{NBSP}500"
    assert format_money(Money(Decimal("100"), "UZS"), "ru") == f"100,00{NBSP}сум"
    assert format_money(Money(Decimal("100"), "UZS"), "uz") == f"100,00{NBSP}soʻm"
    assert format_money(Money(Decimal("100"), "USD"), "uz") == f"100,00{NBSP}USD"
    assert format_value(D, "uz") == "2026-yil 28-oktabr"
    assert format_value(7, "ru") == "7"
    assert format_value("как есть", "ru") == "как есть"


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        ("20608000", "UZS", "Двадцать миллионов шестьсот восемь тысяч сум 00 тийин"),
        ("1", "RUB", "Один рубль 00 копеек"),
        ("2.01", "RUB", "Два рубля 01 копейка"),
        ("21000", "UZS", "Двадцать одна тысяча сум 00 тийин"),
        ("1234567.89", "USD", "Один миллион двести тридцать четыре тысячи пятьсот шестьдесят семь долларов 89 центов"),
        ("0", "UZS", "Ноль сум 00 тийин"),
        ("-5", "UZS", "минус Пять сум 00 тийин"),
        ("12.5", "CNY", "Двенадцать CNY 50/100"),
    ],
)
def test_amount_in_words_ru_matches_erp_format(value: str, currency: str, expected: str) -> None:
    assert amount_in_words(value, currency, "ru") == expected


@pytest.mark.parametrize(
    ("value", "currency", "expected"),
    [
        ("1200000", "UZS", "Bir million ikki yuz ming soʻm 00 tiyin"),
        ("152340000", "UZS", "Bir yuz ellik ikki million uch yuz qirq ming soʻm 00 tiyin"),
        ("1234567.89", "UZS", "Bir million ikki yuz oʻttiz toʻrt ming besh yuz oltmish yetti soʻm 89 tiyin"),
        ("90", "UZS", "Toʻqson soʻm 00 tiyin"),
        ("19", "USD", "Oʻn toʻqqiz AQSH dollari 00 sent"),
        ("0.5", "UZS", "Nol soʻm 50 tiyin"),
        ("3000000000", "EUR", "Uch milliard yevro 00 sent"),
        ("7", "CNY", "Yetti CNY 00/100"),
    ],
)
def test_amount_in_words_uz_latin(value: str, currency: str, expected: str) -> None:
    words = amount_in_words(value, currency, "uz")
    assert words == expected
    assert "'" not in words and "‘" not in words, "узбекская латиница — только ʻ (U+02BB)"


def test_amount_in_words_en_and_garbage() -> None:
    assert amount_in_words("1", "USD", "en") == "One dollar 00 cents"
    assert amount_in_words("21.01", "USD", "en") == "Twenty-one dollars 01 cent"
    assert amount_in_words(None, "UZS", "ru") == "—"
    assert amount_in_words("abc", "UZS", "uz") == "—"
    assert amount_in_words("NaN", "UZS", "en") == "—"
    assert amount_in_words("1" + "0" * 30, "UZS", "ru") == "—"
