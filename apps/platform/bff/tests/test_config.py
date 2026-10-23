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
