"""Публичные адреса из окружения (W15-H8a): Платформа и CRM для ссылок в письмах."""

import pytest

from app.config import Settings
from app.domain.public_urls import is_local_url, is_schema_default, public_url


@pytest.mark.parametrize(
    ("url", "domain", "expected"),
    [
        ("https://platform.example.com/", "", "https://platform.example.com"),
        (
            "http://platform.localhost:8088",
            "platform.example.com",
            "http://platform.localhost:8088",
        ),
        ("", "platform.example.com", "https://platform.example.com"),
        ("", " platform.example.com/ ", "https://platform.example.com"),
        ("", "http://platform.example.com", "http://platform.example.com"),
        ("", "", None),
        ("  ", " ", None),
    ],
)
def test_public_url(url: str, domain: str, expected: str | None) -> None:
    assert public_url(url, domain) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost", True),
        ("http://localhost/", True),
        ("", True),
        ("https://crm.example.com", False),
        ("http://localhost:5173", False),  # явный выбор админа (порт) не трогаем
    ],
)
def test_is_schema_default(url: str, expected: bool) -> None:
    assert is_schema_default(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost", True),
        ("https://127.0.0.1:8443", True),
        ("http://platform.localhost:8088", True),
        ("http://[::1]/", True),
        ("https://platform.example.com", False),
        ("", False),
    ],
)
def test_is_local_url(url: str, expected: bool) -> None:
    assert is_local_url(url) is expected


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_settings_platform_url_from_explicit_url_then_domain() -> None:
    assert make().platform_base_url is None
    assert make(platform_domain="platform.example.com").platform_base_url == (
        "https://platform.example.com"
    )
    explicit = make(
        platform_public_url="http://platform.localhost:8088", platform_domain="p.example.com"
    )
    assert explicit.platform_base_url == "http://platform.localhost:8088"


def test_settings_crm_default_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make().crm_base_url_default is None
    monkeypatch.setenv("CRM_DOMAIN", "crm.example.com")
    assert make().crm_base_url_default == "https://crm.example.com"
    monkeypatch.setenv("CRM_PUBLIC_URL", "http://crm.localhost:8088")
    assert make().crm_base_url_default == "http://crm.localhost:8088"
