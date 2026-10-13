"""Точка расширения «коннектор ERP настроен» (ADR-0022, ADR-0018): адрес + токен (БД, иначе env)."""

import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.domain.erp_connector import normalize_base_url
from app.integrations.erp import erp_connector_configured, resolve_connection, resolve_erp
from app.security.secrets_store import (
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    SecretCipher,
    SecretsStore,
)


class _Store(SecretsStore):
    def __init__(
        self,
        stored: str | None,
        *,
        enabled: bool = True,
        broken: bool = False,
        webhook: str | None = None,
    ) -> None:
        cipher = SecretCipher(secrets.token_hex(32)) if enabled else None
        super().__init__(None, cipher)  # type: ignore[arg-type]
        self._stored = {ERP_SERVICE_TOKEN: stored, ERP_WEBHOOK_SECRET: webhook}
        self._broken = broken

    async def get(self, key: str) -> str | None:
        if self._broken:
            raise RuntimeError("db down")
        return self._stored.get(key)


class _SettingsService:
    """`SettingsService.get()` только с ключом `integrations`; `broken` — БД недоступна."""

    def __init__(self, base_url: str, *, broken: bool = False) -> None:
        self._base_url = base_url
        self._broken = broken

    async def get(self) -> Any:
        if self._broken:
            raise RuntimeError("db down")
        return SimpleNamespace(integrations=SimpleNamespace(erp_base_url=self._base_url))


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
    # Префикс интеграционного API отбрасывается: его добавляет код (`domain/erp_connector`).
    assert connection.base_url == normalize_base_url(base_url) == "https://erp.example"
    assert await erp_connector_configured(_Store(stored, enabled=enabled), config)


async def test_db_failure_falls_back_to_env() -> None:
    config = Settings(
        _env_file=None, erp_base_url="https://erp.example", erp_service_token="env-token"
    )
    connection = await resolve_connection(_Store(None, broken=True), config)
    assert connection is not None
    assert connection.token == "env-token"


async def test_default_settings_mean_not_configured() -> None:
    """Без адреса и токена коннектора нет: жизненный цикл в режиме `local`."""
    assert not await erp_connector_configured(_Store(None, enabled=False), Settings(_env_file=None))


@pytest.mark.parametrize(
    ("db_url", "env_url", "expected", "source"),
    [
        ("https://erp.db/", "https://erp.env", "https://erp.db", "db"),
        ("", "https://erp.env", "https://erp.env", "env"),
        ("", "", "", "none"),
    ],
)
async def test_base_url_from_settings_then_env(
    db_url: str, env_url: str, expected: str, source: str
) -> None:
    """Адрес из «Подключений» (settings) имеет приоритет над `ERP_BASE_URL`."""
    config = Settings(_env_file=None, erp_base_url=env_url, erp_service_token="env-token")
    resolved = await resolve_erp(_Store(None), config, _SettingsService(db_url))  # type: ignore[arg-type]
    assert (resolved.base_url, resolved.base_url_source) == (expected, source)
    assert (resolved.token, resolved.token_source) == ("env-token", "env")
    assert (resolved.connection is not None) is bool(expected)


async def test_settings_db_failure_falls_back_to_env_url() -> None:
    config = Settings(_env_file=None, erp_base_url="https://erp.env", erp_service_token="t")
    settings = _SettingsService("x", broken=True)
    resolved = await resolve_erp(_Store(None), config, settings)  # type: ignore[arg-type]
    assert (resolved.base_url, resolved.base_url_source) == ("https://erp.env", "env")


async def test_webhook_secret_sources() -> None:
    """Секрет вебхуков не влияет на «настроен» (нужен приёмнику M3-CRM-04), но источник виден."""
    config = Settings(_env_file=None, erp_webhook_secret="env-hook")
    from_db = await resolve_erp(_Store(None, webhook="db-hook"), config)
    assert (from_db.webhook_secret, from_db.webhook_secret_source) == ("db-hook", "db")
    from_env = await resolve_erp(_Store(None), config)
    assert (from_env.webhook_secret, from_env.webhook_secret_source) == ("env-hook", "env")
    nothing = await resolve_erp(_Store(None), Settings(_env_file=None))
    assert (nothing.webhook_secret, nothing.webhook_secret_source) == ("", "none")
    assert nothing.connection is None
