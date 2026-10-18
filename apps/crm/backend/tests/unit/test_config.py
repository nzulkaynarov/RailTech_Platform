import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_point_to_compose_services() -> None:
    settings = make()
    assert settings.postgres_host == "postgres"
    assert str(settings.s3_endpoint) == "http://rustfs:9000/"
    assert str(settings.litellm_base_url) == "http://litellm:4000/"
    assert settings.log_format == "json"


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("simple", "simple"),
        ("p@ss:w/rd", "p%40ss%3Aw%2Frd"),
        ("", ""),
    ],
)
def test_dsn_quotes_credentials(password: str, expected: str) -> None:
    settings = make(postgres_password=SecretStr(password), postgres_host="db", postgres_port=5433)
    assert settings.sqlalchemy_url == f"postgresql+psycopg://railtech:{expected}@db:5433/railtech"
    assert settings.libpq_dsn == f"postgresql://railtech:{expected}@db:5433/railtech"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("PLATFORM_SSO_SECRET", "sso-secret-from-env")
    monkeypatch.setenv("POSTGRES_DB", "crm")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = make()
    assert (settings.app_env, settings.postgres_db, settings.log_level) == ("prod", "crm", "DEBUG")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_env", "staging"),
        ("log_format", "xml"),
        ("ready_check_timeout_s", 0),
        ("s3_endpoint", "not-a-url"),
    ],
)
def test_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_password_is_not_exposed_in_repr() -> None:
    settings = make(postgres_password=SecretStr("very-secret-value"))
    assert "very-secret-value" not in repr(settings)


def test_prod_requires_platform_sso_secret() -> None:
    """FIX-01 (аудит S-1): ключа SSO по умолчанию нет — prod без него не стартует."""
    with pytest.raises(ValidationError, match="PLATFORM_SSO_SECRET"):
        make(app_env="prod")


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_sso_is_off_without_secret_outside_prod(app_env: str) -> None:
    assert make(app_env=app_env).platform_sso_secrets == []


def test_sso_secrets_support_rotation() -> None:
    settings = make(platform_sso_secret=SecretStr(" new-key , old-key ,"))
    assert settings.platform_sso_secrets == ["new-key", "old-key"]
