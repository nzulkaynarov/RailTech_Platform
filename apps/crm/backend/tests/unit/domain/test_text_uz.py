"""Узбекская латиница в ответах модели: новый алфавит Ö Ğ Ş Ç и ʼ (владелец 2026-11-17)."""

import pytest

from app.domain.text import normalize_uzbek


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Narxi xizmatga bog'liq", "Narxi xizmatga boğliq"),
        ("O'zbekiston va g'alla", "Özbekiston va ğalla"),
        ("ma'lumot va ta’minot", "maʼlumot va taʼminot"),
        ("Allaqachon töğri: ö va ğ", "Allaqaçon töğri: ö va ğ"),
        ("RT-Track 'paket' narxi", "RT-Track 'paket' narxi"),
    ],
)
def test_normalize_uzbek(raw: str, expected: str) -> None:
    assert normalize_uzbek(raw) == expected
