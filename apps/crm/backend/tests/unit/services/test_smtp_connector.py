"""Коннектор «Почта» (M3-CRM-08): сохранение с паролем, «Проверить связь», секреты не утекают."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.smtp import SmtpCheck, SmtpConnection, SmtpProbeError
from app.schemas.integrations import SmtpStatusOut
from app.schemas.settings import AppSettings
from app.security.passwords import hash_password
from app.security.principal import Principal
from app.security.secrets_store import (
    SMTP_PASSWORD,
    SMTP_USERNAME,
    SecretCipher,
    SecretsStore,
    SecretStatus,
)
from app.services import smtp_connector as svc
from app.services.mail import MailService

RELAY_PASSWORD = "relay-password-for-unit-tests-Q1w2"
PASSWORD = "admin-pass-123"
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


def fake_sessions() -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    return factory


class FakeStore(SecretsStore):
    def __init__(self, stored: dict[str, str] | None = None, *, enabled: bool = True) -> None:
        cipher = SecretCipher("k" * 40) if enabled else None
        super().__init__(fake_sessions(), cipher)
        self.saved: dict[str, str] = dict(stored or {})

    async def get(self, key: str) -> str | None:
        return self.saved.get(key) if self.enabled else None

    async def put(self, session: Any, key: str, value: str, user_id: int | None) -> None:
        self.saved[key] = value

    async def status(self, key: str) -> SecretStatus | None:
        value = self.saved.get(key)
        return None if value is None else SecretStatus(value[-4:], None)  # type: ignore[arg-type]


class FakeSettings:
    def __init__(self, smtp: dict[str, Any] | None = None) -> None:
        self.smtp = smtp or {}
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def get(self) -> AppSettings:
        return AppSettings.model_validate({"integrations": {"smtp": self.smtp}})

    async def update(self, key: str, value: dict[str, Any], user_id: int | None) -> Any:
        self.updates.append((key, value))
        self.smtp = value["smtp"]
        return value


class FakeTransport:
    def __init__(self, error: SmtpProbeError | None = None) -> None:
        self.error = error
        self.checked: list[SmtpConnection] = []

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        self.checked.append(connection)
        if self.error is not None:
            raise self.error
        return SmtpCheck("relay.example ESMTP", bool(connection.username), 12)

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        raise AssertionError("«Проверить связь» не отправляет писем")


@pytest.fixture
def audit_log(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    async def record(*args: Any, **kwargs: Any) -> None:
        records.append({"args": args, **kwargs})

    user = SimpleNamespace(
        id=1,
        email="admin@railtech.uz",
        full_name="Админ",
        password_hash=hash_password(PASSWORD),
        failed_logins=0,
        locked_until=None,
    )

    async def get_user(session: Any, user_id: int, **_: Any) -> Any:
        return user

    monkeypatch.setattr("app.services.smtp_connector.audit.record", record)
    monkeypatch.setattr("app.services.smtp_connector.users_repo.get", get_user)
    return records


def build(
    *,
    store: FakeStore | None = None,
    settings: FakeSettings | None = None,
    transport: FakeTransport | None = None,
) -> tuple[svc.SmtpConnectorService, FakeStore, FakeSettings, FakeTransport, list[int]]:
    store = store or FakeStore()
    settings = settings or FakeSettings()
    transport = transport or FakeTransport()
    queued: list[int] = []

    async def enqueue(email_log_id: int) -> int:
        queued.append(email_log_id)
        return email_log_id

    mail = MailService(
        fake_sessions(),
        store,
        store._cipher,
        Settings(_env_file=None),
        settings,  # type: ignore[arg-type]
        transport,
        enqueue,
    )
    service = svc.SmtpConnectorService(fake_sessions(), settings, store, mail)  # type: ignore[arg-type]
    return service, store, settings, transport, queued


async def test_not_configured_status_and_check_409() -> None:
    service, *_ = build()
    status = await service.status()
    assert (status.configured, status.settings_source, status.password_configured) == (
        False,
        "none",
        False,
    )
    with pytest.raises(ConflictError) as info:
        await service.check()
    assert info.value.details["reason"] == Reason.SMTP_NOT_CONFIGURED.value


async def test_save_requires_password_and_hides_secrets(audit_log: list[dict[str, Any]]) -> None:
    service, store, settings, _, _ = build()
    with pytest.raises(ValidationFailedError) as wrong:
        await service.save(
            ADMIN,
            host="smtp.example.com",
            port=587,
            security="starttls",
            from_email="crm@example.com",
            from_name="CRM",
            username="crm",
            password=RELAY_PASSWORD,
            admin_password="nope",
        )
    assert wrong.value.details["reason"] == Reason.WRONG_PASSWORD.value
    assert store.saved == {}
    assert settings.updates == []

    with capture_logs() as logs:
        status = await service.save(
            ADMIN,
            host=" SMTP.Example.com ",
            port=587,
            security="starttls",
            from_email="CRM@Example.com",
            from_name=" RailTech CRM ",
            username="crm",
            password=RELAY_PASSWORD,
            admin_password=PASSWORD,
        )
    assert status.configured is True
    assert (status.host, status.from_email, status.from_name) == (
        "smtp.example.com",
        "crm@example.com",
        "RailTech CRM",
    )
    assert (status.username, status.password_last4, status.password_source) == ("crm", "Q1w2", "db")
    assert store.saved == {SMTP_USERNAME: "crm", SMTP_PASSWORD: RELAY_PASSWORD}
    assert settings.updates[0][1]["smtp"]["host"] == "smtp.example.com"
    # Пароль релея — не в ответе, не в аудите, не в логах.
    out = SmtpStatusOut(**_asdict(status))
    assert RELAY_PASSWORD not in out.model_dump_json()
    (audit,) = audit_log
    assert audit["args"][2] == "integrations.smtp"
    assert RELAY_PASSWORD not in repr(audit)
    assert audit["after"]["smtp_password_last4"] == "Q1w2"
    assert all(RELAY_PASSWORD not in repr(log) for log in logs)


def _asdict(status: svc.SmtpStatus) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(status)


async def test_save_keeps_secrets_when_none_and_validates_host_and_sender() -> None:
    store = FakeStore({SMTP_USERNAME: "old", SMTP_PASSWORD: "old-relay-password-Z9x8"})
    service, store, settings, _, _ = build(store=store)
    for host, from_email, reason, field in [
        ("smtp.example.com:587", "crm@example.com", Reason.SMTP_INVALID_HOST, "host"),
        ("smtp.example.com", "crm@", Reason.INVALID_EMAIL, "from_email"),
    ]:
        with pytest.raises(ValidationFailedError) as info:
            await service.save(
                ADMIN,
                host=host,
                port=587,
                security="starttls",
                from_email=from_email,
                from_name="",
                username=None,
                password=None,
                admin_password=PASSWORD,
            )
        assert info.value.details == {"reason": reason.value, "field": field}
    assert settings.updates == []


async def test_save_secrets_without_secrets_key_is_409() -> None:
    service, *_ = build(store=FakeStore(enabled=False))
    with pytest.raises(ConflictError) as info:
        await service.save(
            ADMIN,
            host="smtp.example.com",
            port=587,
            security="starttls",
            from_email="crm@example.com",
            from_name="",
            username="crm",
            password=RELAY_PASSWORD,
            admin_password=PASSWORD,
        )
    assert info.value.details["reason"] == Reason.SECRETS_KEY_MISSING.value


CONFIGURED = {"host": "smtp.example.com", "from_email": "crm@example.com", "port": 587}


async def test_check_passes_connection_and_returns_server_banner() -> None:
    store = FakeStore({SMTP_USERNAME: "crm", SMTP_PASSWORD: RELAY_PASSWORD})
    service, _, _, transport, _ = build(store=store, settings=FakeSettings(CONFIGURED))
    result = await service.check()
    assert (result.server, result.authenticated, result.latency_ms) == (
        "relay.example ESMTP",
        True,
        12,
    )
    (connection,) = transport.checked
    assert (connection.host, connection.username, connection.password) == (
        "smtp.example.com",
        "crm",
        RELAY_PASSWORD,
    )


@pytest.mark.parametrize(
    ("kind", "reason", "error_type"),
    [
        ("invalid_host", Reason.SMTP_INVALID_HOST, ValidationFailedError),
        ("unavailable", Reason.SMTP_UNAVAILABLE, UpstreamUnavailableError),
        ("auth_failed", Reason.SMTP_AUTH_FAILED, UpstreamUnavailableError),
        ("tls_failed", Reason.SMTP_TLS_FAILED, UpstreamUnavailableError),
        ("rejected", Reason.SMTP_REJECTED, UpstreamUnavailableError),
    ],
)
async def test_check_errors_map_to_reasons(
    kind: Any, reason: Reason, error_type: type[Exception]
) -> None:
    transport = FakeTransport(SmtpProbeError(kind, "detail"))
    service, *_ = build(settings=FakeSettings(CONFIGURED), transport=transport)
    with capture_logs() as logs, pytest.raises(error_type) as info:
        await service.check()
    assert info.value.details["reason"] == reason.value  # type: ignore[attr-defined]
    assert any(log["event"] == "smtp_check_failed" for log in logs)


async def test_test_send_goes_to_admin_through_journal(
    audit_log: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    service, *_ = build(settings=FakeSettings(CONFIGURED))
    sent: list[tuple[str, str, dict[str, str]]] = []

    async def send(template: str, to: str, context: Any, **kwargs: Any) -> Any:
        sent.append((template, to, dict(context)))
        return SimpleNamespace(id=5, to_email=to, status="queued")

    monkeypatch.setattr(service._mail, "send", send)
    view = await service.test_send(ADMIN)
    assert view.id == 5
    assert sent == [
        (
            "test",
            "admin@railtech.uz",
            {"full_name": "Админ", "host": "smtp.example.com", "from_email": "crm@example.com"},
        )
    ]
