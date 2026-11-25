"""СЦ-7: язык запроса — `Accept-Language` с весами и точными тегами."""

import pytest

from app.feeds.lang import parse_language


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "ru"),
        ("", "ru"),
        ("uz", "uz"),
        ("uz-UZ", "uz"),
        ("en-GB,en;q=0.9", "en"),
        ("ru-RU", "ru"),
        ("en;q=0.5, uz;q=0.9", "uz"),
        ("de, fr;q=0.8", "ru"),
        ("uz;q=0, en;q=0.4", "en"),
        ("uzbek", "ru"),
        ("english", "ru"),
        ("uz;q=abc", "ru"),
    ],
)
def test_parse_language_honours_weights_and_exact_tags(header: str | None, expected: str) -> None:
    assert parse_language(header) == expected
