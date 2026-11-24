"""Core converter in app code agrees with the repo script and is idempotent."""

import sys
from pathlib import Path

import pytest

from app.domain.text import normalize_uzbek
from app.domain.uz_alphabet import convert_uz

SAMPLES = [
    "o'zbekcha", "Oʻzbekcha", "bog'liq", "qo'ng'iroq qiling", "Mablag‘ bankka kelib tushgach",
    "shartnoma va chek", "Ma'lumot", "Telegramga yuboring", "Google'da ochiladi",
    "MChJ «Toshkent Logistik»",
    "F.I.Sh. ni kiriting", "https://example.uz/chat", "{name} bilan shaxsiy", "Ch",
    "JShShIR va STIR",
]  # fmt: skip


@pytest.mark.parametrize("text", SAMPLES)
def test_idempotent(text: str) -> None:
    once = convert_uz(text)
    assert convert_uz(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bog'liq", "boğliq"),
        ("bogʻliq", "boğliq"),
        ("o'zbekcha", "özbekça"),
        ("qo'ng'iroq", "qönğiroq"),
        ("ma'lumot", "maʼlumot"),
        ("maʼlumot", "maʼlumot"),
        ("shartnoma, chek", "şartnoma, çek"),
        ("Google'da va Telegramga", "Google'da va Telegramga"),
        ("MChJ «Toshkent Logistik» bilan", "MChJ «Toshkent Logistik» bilan"),
        ("Salom, mijoz!", "Salom, mijoz!"),
    ],
)
def test_normalize_uzbek_new_alphabet(raw: str, expected: str) -> None:
    assert normalize_uzbek(raw) == expected


def test_app_core_matches_script() -> None:
    scripts = Path(__file__).resolve().parents[6] / "scripts"
    if not (scripts / "uz_new_alphabet.py").exists():
        pytest.skip("scripts are not available")
    sys.path.insert(0, str(scripts))
    from uz_new_alphabet import convert_uz as script_convert  # type: ignore[import-not-found]

    for text in SAMPLES:
        assert convert_uz(text) == script_convert(text), text
