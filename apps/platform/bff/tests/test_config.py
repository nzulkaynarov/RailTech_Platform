import ipaddress

import pytest

from app.config import Settings


def test_defaults_point_to_compose_services(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PLATFORM_CRM_URL",
        "PLATFORM_ERP_URL",
        "REDIS_URL",
        "PLATFORM_SESSION_TTL_HOURS",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.crm_url == "http://crm-api:8000"
    assert s.erp_url == "http://erp-backend:8000"
    assert s.redis_url == "redis://redis-cache:6379/0"  # S0-2: сессии на redis-cache
    assert s.session_ttl_hours == 12
    assert s.log_level == "INFO"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_CRM_URL", "http://crm.example:9000")
    monkeypatch.setenv("PLATFORM_SESSION_TTL_HOURS", "4")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings(_env_file=None)
    assert s.crm_url == "http://crm.example:9000"
    assert s.session_ttl_hours == 4
    assert s.log_level == "DEBUG"


def test_crm_timeout_defaults_to_five_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLATFORM_CRM_TIMEOUT_SECONDS", raising=False)
    assert Settings(_env_file=None).crm_timeout_seconds == 5.0


def test_crm_timeout_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_CRM_TIMEOUT_SECONDS", "8.5")
    assert Settings(_env_file=None).crm_timeout_seconds == 8.5


def test_crm_timeout_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_CRM_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="PLATFORM_CRM_TIMEOUT_SECONDS"):
        Settings(_env_file=None)


def test_trusted_proxies_default_covers_the_compose_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLATFORM_TRUSTED_PROXIES", raising=False)
    nets = Settings(_env_file=None).trusted_proxy_networks
    assert any(ipaddress.ip_address("172.18.0.5") in n for n in nets)
    assert not any(ipaddress.ip_address("203.0.113.5") in n for n in nets)


def test_trusted_proxies_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_TRUSTED_PROXIES", "192.0.2.0/24, 198.51.100.7")
    nets = Settings(_env_file=None).trusted_proxy_networks
    assert [str(n) for n in nets] == ["192.0.2.0/24", "198.51.100.7/32"]


def test_trusted_proxies_typo_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_TRUSTED_PROXIES", "10.0.0.0/8, not-a-network")
    with pytest.raises(ValueError, match="PLATFORM_TRUSTED_PROXIES"):
        Settings(_env_file=None)
