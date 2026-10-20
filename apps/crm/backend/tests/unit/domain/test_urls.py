"""Адреса кнопок бота: только http(s) с хостом (FIX-34)."""

import pytest

from app.domain.urls import is_http_url


@pytest.mark.parametrize(
    "value",
    [
        "https://cabinet.example.com",
        "http://localhost:8088/quotes/42",
        "https://erp.example.com/q/42?token=abc",
    ],
)
def test_http_urls_pass(value: str) -> None:
    assert is_http_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "javascript:alert(1)",
        "ftp://example.com/file",
        "tg://resolve?domain=bot",
        "cabinet.example.com",
        "https://",
        "https://exa mple.com",
        " https://example.com",
        "https://example.com ",
        None,
        42,
    ],
)
def test_other_values_are_rejected(value: object) -> None:
    assert not is_http_url(value)
