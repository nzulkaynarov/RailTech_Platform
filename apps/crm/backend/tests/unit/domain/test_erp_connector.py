"""Адрес интеграционного API ERP (M3-CRM-02): нормализация, проверка, URL пробы."""

import pytest

from app.domain.erp_connector import base_url_problem, health_url, normalize_base_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://erp.example.com", "https://erp.example.com"),
        ("  https://erp.example.com/  ", "https://erp.example.com"),
        ("https://erp.example.com/api/integration/v1", "https://erp.example.com"),
        ("https://erp.example.com/api/integration/v1/", "https://erp.example.com"),
        ("https://erp.example.com/API/Integration/V1", "https://erp.example.com"),
        ("http://erp.localhost", "http://erp.localhost"),
        ("http://erp.localhost:8010/base", "http://erp.localhost:8010/base"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://erp.example.com", True),
        ("http://erp.localhost", True),
        ("http://127.0.0.1:8010", True),
        ("", False),
        ("erp.example.com", False),
        ("ftp://erp.example.com", False),
        ("https://", False),
        ("https://erp.example.com?x=1", False),
        ("https://erp.example.com#top", False),
        ("https://user:pass@erp.example.com", False),
        ("https://[bad", False),
    ],
)
def test_base_url_problem(url: str, ok: bool) -> None:
    assert (base_url_problem(url) is None) is ok


def test_health_url_adds_integration_prefix_once() -> None:
    assert health_url("https://erp.example.com") == (
        "https://erp.example.com/api/integration/v1/health"
    )
    assert health_url("https://erp.example.com/api/integration/v1/") == (
        "https://erp.example.com/api/integration/v1/health"
    )
