"""Точка расширения «коннектор ERP настроен» (ADR-0022, ADR-0018): адрес + токен (БД, иначе env)."""

import secrets

import pytest

from app.config import Settings
from app.integrations.erp import erp_connector_configured, resolve_connection
from app.security.secrets_store import SecretCipher, SecretsStore


class _Store(SecretsStore):
    def __init__(self, stored: str | None, *, enabled: bool = True, broken: bool = False) -> None:
        cipher = SecretCipher(secrets.token_hex(32)) if enabled else None
        super().__init__(None, cipher)  # type: ignore[arg-type]
        self._stored = stored
        self._broken = broken

    async def get(self, key: str) -> str | None:
        if self._broken:
            raise RuntimeError("db down")
        return self._stored


@pytest.mark.parametrize(
    ("base_url", "stored", "enabled", "env", "expected_token"),
    [
        (
            "https://erp.example/api/integration/v1",
            "db-token-value-1",
            True,
            "env-token",
            "db-token-value-1",
        ),
        ("https://erp.example/api/integration/v1", None, True, "env-token", "env-token"),
        (
            "https://erp.example/api/integration/v1",
            "db-token-value-1",
            False,
            "env-token",
            "env-token",
        ),
        (
            "https://erp.example/api/integration/v1/",
            "db-token-value-1",
            True,
            "",
            "db-token-value-1",
        ),
        ("https://erp.example/api/integration/v1", None, True, "", None),
        ("", "db-token-value-1", True, "env-token", None),
        ("   ", None, False, "env-token", None),
    ],
)
async def test_connection_resolution(
    base_url: str, stored: str | None, enabled: bool, env: str, expected_token: str | None
) -> None:
    config = Settings(_env_file=None, erp_base_url=base_url, erp_service_token=env)
    connection = await resolve_connection(_Store(stored, enabled=enabled), config)
    if expected_token is None:
        assert connection is None
        assert not await erp_connector_configured(_Store(stored, enabled=enabled), config)
        return
    assert connection is not None
    assert connection.token == expected_token
    assert connection.base_url == base_url.strip().rstrip("/")
    assert await erp_connector_configured(_Store(stored, enabled=enabled), config)


async def test_db_failure_falls_back_to_env() -> None:
    config = Settings(
        _env_file=None, erp_base_url="https://erp.example", erp_service_token="env-token"
    )
    connection = await resolve_connection(_Store(None, broken=True), config)
    assert connection is not None
    assert connection.token == "env-token"


async def test_default_settings_mean_not_configured() -> None:
    """До M3-CRM-02 коннектора нет: жизненный цикл в режиме `local`."""
    assert not await erp_connector_configured(_Store(None, enabled=False), Settings(_env_file=None))
