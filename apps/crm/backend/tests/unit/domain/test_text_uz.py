"""Узбекская латиница в ответах модели: oʻ/gʻ и ʼ (аудит 2026-10-12)."""

import pytest

from app.domain.text import normalize_uzbek


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Narxi xizmatga bog'liq", "Narxi xizmatga bogʻliq"),
        ("O'zbekiston va g'alla", "Oʻzbekiston va gʻalla"),
        ("ma'lumot va ta’minot", "maʼlumot va taʼminot"),
        ("Allaqachon toʻgʻri: oʻ va gʻ", "Allaqachon toʻgʻri: oʻ va gʻ"),
        ("RT-Track 'paket' narxi", "RT-Track 'paket' narxi"),
    ],
)
def test_normalize_uzbek(raw: str, expected: str) -> None:
    assert normalize_uzbek(raw) == expected
