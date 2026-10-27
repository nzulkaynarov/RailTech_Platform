"""Журнал аудита: маска секретных значений в `before`/`after` (W13-A6, контракт 0.12.0).

Правила — `app/schemas_audit.py`: длинные основы ищутся подстрокой (склейки `accesstoken`,
`newpassword`), короткие (`key`, `pin`, `pwd`, `otp`, `cvv`, `jwt`, `dsn`) — целым словом с
отрезанием хвостовых цифр; значение под секретным именем скрывается целиком, любого типа.
Явные исключения: имена-коды (`service_key`…), признаки итога и метаданные (видны только как флаг,
число или `null`), `*_last4` (видна только строка до 4 символов). Ложноположительные
(`idempotency_key`, `token_expires_at`) безопаснее скрыть, чем раскрыть.
"""

import pytest

from app.schemas_audit import is_hidden, is_secret_key, key_policy, normalize_key, redact

SECRET_NAMES = [
    # прежние формы
    "password",
    "Password",
    "passwd",
    "pwd",
    "secret",
    "client_secret",
    "token",
    "access_token",
    "refreshToken",
    "key",
    "api_key",
    "apiKey",
    "API-KEY",
    "api key",
    "apikey",
    "litellm_api_key",
    "private_key",
    "privateKey",
    "ssh_key",
    "encryption_key",
    "keys",
    "authorization",
    "Authorization",
    "credentials",
    "credential",
    "pin",
    "pin_code",
    "smtp.password",
    # склейки (старый шаблон ловил их подстрокой)
    "accesstoken",
    "authtoken",
    "refreshtoken",
    "clientsecret",
    "newpassword",
    "oldpassword",
    "passwordhash",
    "passphrase",
    "passcode",
    # хвостовые цифры
    "password1",
    "token2",
    "key1",
    "pin2",
    "pwd3",
    "api_key_2",
    # новые основы
    "otp",
    "otp_code",
    "cvv",
    "cvv2",
    "jwt",
    "access_jwt",
    "cookie",
    "session_cookie",
    "bearer",
    "bearer_token",
    "signature",
    "webhook_signature",
    "hmac",
    "hmac_secret",
    "dsn",
    "sentry_dsn",
    "database_url",
    "DatabaseURL",
    "databaseUrl",
]

VALUES = [
    ("str", "swordfish"),
    ("int", 123456),
    ("bool", True),
    ("list", ["a", "b"]),
    ("dict", {"inner": "x", "n": 1}),
    ("zero", 0),
    ("false", False),
    ("float", 3.14),
]


@pytest.mark.parametrize("name", SECRET_NAMES)
@pytest.mark.parametrize("value", [v for _, v in VALUES], ids=[i for i, _ in VALUES])
def test_whole_value_of_a_secret_name_is_masked(name: str, value: object) -> None:
    assert is_secret_key(name)
    assert key_policy(name) == "mask"
    assert redact({name: value}) == {name: "***"}


@pytest.mark.parametrize(
    "name",
    [
        "host",
        "email",
        "name",
        "description",
        "position",
        "stage",
        "keyboard",
        "monkey",
        "pinned",
        "spinner",
        "optional",
        "dsnx",
    ],
)
def test_ordinary_names_are_open(name: str) -> None:
    assert key_policy(name) == "open"
    assert redact({name: "значение"}) == {name: "значение"}


@pytest.mark.parametrize(
    "name",
    [
        "service_key",
        "product_key",
        "settings_key",
        "setting_key",
        "section_key",
        "agent_context_key",
        "Settings-Key",
        "settingsKey",
    ],
)
def test_code_like_names_are_kept_with_any_value(name: str) -> None:
    assert key_policy(name) == "open"
    assert redact({name: "значение"}) == {name: "значение"}


@pytest.mark.parametrize(
    "name",
    [
        "password_changed",
        "token_set",
        "key_configured",
        "api_key_present",
        "keys_rotated",
        "secrets_key_missing",
        "secrets_key_changed",
        "must_change_password",
        "has_password",
        "max_tokens",
        "prompt_tokens",
        "completion_tokens",
    ],
)
def test_flags_and_counters_pass_only_as_flag_number_or_null(name: str) -> None:
    assert key_policy(name) == "scalar"
    for ok in (True, False, 0, 7, 3.5, None):
        assert redact({name: ok}) == {name: ok}
    for bad in ("кто-то-вставил-пароль", ["x"], {"x": 1}):
        assert redact({name: bad}) == {name: "***"}


def test_password_changed_with_a_string_is_masked() -> None:
    assert redact({"password_changed": "Tmp-secret-1"}) == {"password_changed": "***"}


@pytest.mark.parametrize("name", ["password_last4", "api_key_last4", "token_last4", "apiKeyLast4"])
def test_last4_passes_only_a_short_string(name: str) -> None:
    assert key_policy(name) == "last4"
    assert redact({name: "9f3c"}) == {name: "9f3c"}
    assert redact({name: "ab"}) == {name: "ab"}
    assert redact({name: "sk-live-123456"}) == {name: "***"}
    assert redact({name: 1234}) == {name: "***"}
    assert redact({name: ["9f3c"]}) == {name: "***"}


def test_idempotency_key_and_similar_false_positives_are_hidden_rather_than_shown() -> None:
    assert redact({"idempotency_key": "abc-1", "token_expires_at": "2026-10-26T10:00:00Z"}) == {
        "idempotency_key": "***",
        "token_expires_at": "***",
    }


def test_empty_secret_values_stay_empty() -> None:
    assert redact({"token": "", "password": None, "api_key": ""}) == {
        "token": "",
        "password": None,
        "api_key": "",
    }


def test_redact_goes_through_lists_and_nested_dicts() -> None:
    value = {"a": [{"b": {"private_key": "-----BEGIN-----"}}, "text"], "pin": 1234}

    assert redact(value) == {"a": [{"b": {"private_key": "***"}}, "text"], "pin": "***"}


def test_is_hidden_decides_by_name_and_value() -> None:
    assert is_hidden("password", "x")
    assert not is_hidden("password", None)
    assert not is_hidden("host", "x")
    assert not is_hidden("password_changed", True)
    assert is_hidden("password_changed", "x")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("apiKey", "api_key"),
        ("API-KEY", "api_key"),
        ("api key", "api_key"),
        ("DatabaseURL", "database_url"),
    ],
)
def test_normalize_key(raw: str, expected: str) -> None:
    assert normalize_key(raw) == expected
