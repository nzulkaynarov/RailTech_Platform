import pytest

from app.domain.text import normalize_question


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Сколько стоит?", "сколько стоит"),
        ("  СКОЛЬКО   стоит ?? ", "сколько стоит"),
        ("Ёлка", "елка"),
        ("O‘zbekiston’da", "o'zbekiston'da"),
        ("Price, please!", "price please"),
    ],
)
def test_normalize_question(raw: str, expected: str) -> None:
    assert normalize_question(raw) == expected
