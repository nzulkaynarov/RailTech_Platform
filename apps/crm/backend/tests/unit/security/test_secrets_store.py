"""Шифрование секретов интеграций: round-trip, чужой ключ, отсутствие ключа, last4."""

import secrets

import pytest

from app.config import Settings
from app.integrations.telegram import resolve_token
from app.security.secrets_store import SecretCipher, SecretsKeyError, SecretsStore, last4

PLAINTEXT = "123456:fake-token-for-unit-tests-xyz9"


def test_round_trip_and_ciphertext_hides_plaintext() -> None:
    cipher = SecretCipher(secrets.token_hex(32))
    encrypted = cipher.encrypt(PLAINTEXT)
    assert PLAINTEXT.encode() not in encrypted
    assert cipher.decrypt(encrypted) == PLAINTEXT


def test_other_key_cannot_decrypt() -> None:
    encrypted = SecretCipher(secrets.token_hex(32)).encrypt(PLAINTEXT)
    with pytest.raises(SecretsKeyError):
        SecretCipher(secrets.token_hex(32)).decrypt(encrypted)


@pytest.mark.parametrize("key", ["", "too-short-key"])
def test_missing_or_invalid_key_disables_store(key: str) -> None:
    with pytest.raises(SecretsKeyError):
        SecretCipher(key)
    assert SecretCipher.optional(key) is None


@pytest.mark.parametrize(
    ("value", "expected"), [(PLAINTEXT, "xyz9"), ("short", "****"), ("", "****")]
)
def test_last4(value: str, expected: str) -> None:
    assert last4(value) == expected


class _Store(SecretsStore):
    def __init__(self, stored: str | None, *, enabled: bool = True) -> None:
        cipher = SecretCipher(secrets.token_hex(32)) if enabled else None
        super().__init__(None, cipher)  # type: ignore[arg-type]
        self._stored = stored

    async def get(self, key: str) -> str | None:
        return self._stored


@pytest.mark.parametrize(
    ("stored", "enabled", "env", "expected"),
    [
        ("111:db-token-value-aaaaaaaaaa", True, "222:env-token-value", "db"),
        (None, True, "222:env-token-value", "env"),
        ("111:db-token-value-aaaaaaaaaa", False, "222:env-token-value", "env"),
        (None, True, "", "none"),
    ],
)
async def test_token_resolution_order(
    stored: str | None, enabled: bool, env: str, expected: str
) -> None:
    config = Settings(_env_file=None, telegram_bot_token=env)
    token, source = await resolve_token(_Store(stored, enabled=enabled), config)
    assert source == expected
    assert token == {"db": stored, "env": env, "none": ""}[expected]
