import pytest

from app.domain.text import limit_words, normalize_question


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


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("Коротко.", 120, "Коротко."),
        ("Один два три. Четыре пять шесть. Семь восемь?", 6, "Один два три. Четыре пять шесть."),
        (
            "Первое длинное предложение из пяти слов. Второе.",
            2,
            "Первое длинное предложение из пяти слов.",
        ),
        ("Абзац один.\n\nАбзац два тут. Три.", 5, "Абзац один.\n\nАбзац два тут."),
    ],
)
def test_limit_words_cuts_at_sentence_boundary(text: str, limit: int, expected: str) -> None:
    assert limit_words(text, limit) == expected
