"""Транспорт SMTP (M3-CRM-08): `smtplib` замокан — EHLO/STARTTLS/AUTH, классы ошибок, письмо."""

import smtplib
import socket
from dataclasses import replace
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from app.config import Settings
from app.integrations.smtp import SmtpConnection, SmtplibTransport, SmtpProbeError, resolve_smtp
from app.security.secrets_store import SMTP_PASSWORD, SMTP_USERNAME, SecretsStore

CONN = SmtpConnection(
    host="smtp.example.com",
    port=587,
    security="starttls",
    username="crm",
    password="relay-pass-for-unit-tests",
    from_email="crm@example.com",
    from_name="RailTech CRM",
)


class FakeSmtp:
    """Подмена `smtplib.SMTP`/`SMTP_SSL`: журнал вызовов и ошибки по сценарию."""

    instances: ClassVar[list["FakeSmtp"]] = []
    scenario: ClassVar[dict[str, Exception]] = {}

    def __init__(self, host: str, port: int, timeout: float, context: Any = None) -> None:
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[str] = []
        self.ehlo_resp = b"smtp.example.com Hello\nAUTH LOGIN PLAIN"
        self.sent: list[EmailMessage] = []
        FakeSmtp.instances.append(self)
        if "connect" in FakeSmtp.scenario:
            raise FakeSmtp.scenario["connect"]

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")
        if "starttls" in FakeSmtp.scenario:
            raise FakeSmtp.scenario["starttls"]

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")
        if "login" in FakeSmtp.scenario:
            raise FakeSmtp.scenario["login"]

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append("send")
        if "send" in FakeSmtp.scenario:
            raise FakeSmtp.scenario["send"]
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _fake_smtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances.clear()
    FakeSmtp.scenario = {}
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)


async def test_check_does_ehlo_starttls_auth_and_quit_without_sending() -> None:
    result = await SmtplibTransport().check(CONN)
    assert result.authenticated is True
    assert result.server == "smtp.example.com Hello"
    (client,) = FakeSmtp.instances
    assert client.calls == ["ehlo", "starttls", "ehlo", "login:crm", "quit"]
    assert client.sent == []


async def test_check_without_username_skips_auth_and_ssl_skips_starttls() -> None:
    conn = replace(CONN, username="", password="", security="ssl")
    result = await SmtplibTransport().check(conn)
    assert result.authenticated is False
    assert FakeSmtp.instances[0].calls == ["ehlo", "quit"]


async def test_send_builds_message_with_sender_and_subject() -> None:
    await SmtplibTransport().send(CONN, "aziz@railtech.uz", "Тема письма", "Текст\n")
    (client,) = FakeSmtp.instances
    (message,) = client.sent
    assert message["From"] == "RailTech CRM <crm@example.com>"
    assert message["To"] == "aziz@railtech.uz"
    assert message["Subject"] == "Тема письма"
    assert message.get_content() == "Текст\n"
    assert "login:crm" in client.calls


@pytest.mark.parametrize(
    ("step", "error", "kind"),
    [
        ("connect", socket.gaierror("name or service not known"), "unavailable"),
        ("connect", TimeoutError(), "unavailable"),
        ("connect", ConnectionRefusedError(), "unavailable"),
        ("starttls", smtplib.SMTPNotSupportedError("no STARTTLS"), "tls_failed"),
        ("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"), "auth_failed"),
        ("login", smtplib.SMTPNotSupportedError("no AUTH"), "auth_failed"),
        ("send", smtplib.SMTPRecipientsRefused({"x@y.z": (550, b"no such user")}), "rejected"),
        ("send", smtplib.SMTPDataError(552, b"too big"), "rejected"),
        ("send", smtplib.SMTPServerDisconnected("gone"), "unavailable"),
    ],
)
async def test_errors_are_classified(step: str, error: Exception, kind: str) -> None:
    FakeSmtp.scenario = {step: error}
    transport = SmtplibTransport()
    with pytest.raises(SmtpProbeError) as info:
        await (transport.send(CONN, "x@y.z", "s", "b") if step == "send" else transport.check(CONN))
    assert info.value.kind == kind


async def test_invalid_host_is_rejected_before_connecting() -> None:
    conn = replace(CONN, host="smtp.example.com:587")
    with pytest.raises(SmtpProbeError) as info:
        await SmtplibTransport().check(conn)
    assert info.value.kind == "invalid_host"
    assert FakeSmtp.instances == []


# --- Откуда берутся настройки: «Подключения» → .env ------------------------------------------


class _Store(SecretsStore):
    def __init__(self, stored: dict[str, str] | None = None, *, enabled: bool = True) -> None:
        from app.security.secrets_store import SecretCipher

        cipher = SecretCipher("k" * 40) if enabled else None
        super().__init__(None, cipher)  # type: ignore[arg-type]
        self._stored = stored or {}

    async def get(self, key: str) -> str | None:
        return self._stored.get(key)


class _Settings:
    def __init__(self, host: str = "", from_email: str = "crm@db.example") -> None:
        self._host, self._from = host, from_email

    async def get(self) -> Any:
        from app.schemas.settings import AppSettings

        return AppSettings.model_validate(
            {"integrations": {"smtp": {"host": self._host, "from_email": self._from, "port": 465}}}
        )


async def test_db_settings_win_over_env_and_env_is_fallback() -> None:
    config = Settings(
        _env_file=None,
        smtp_host="env.example",
        smtp_from_email="env@example.com",
        smtp_username="env-user",
        smtp_password="env-pass",
    )
    store = _Store({SMTP_USERNAME: "db-user", SMTP_PASSWORD: "db-pass-value"})
    resolved = await resolve_smtp(store, config, _Settings("DB.example"))  # type: ignore[arg-type]
    assert (resolved.host, resolved.port, resolved.settings_source) == ("db.example", 465, "db")
    assert (resolved.username, resolved.username_source) == ("db-user", "db")
    assert (resolved.password, resolved.password_source) == ("db-pass-value", "db")
    assert resolved.connection is not None

    fallback = await resolve_smtp(_Store(enabled=False), config, _Settings(""))  # type: ignore[arg-type]
    assert (fallback.host, fallback.port, fallback.settings_source) == ("env.example", 587, "env")
    assert (fallback.username_source, fallback.password_source) == ("env", "env")


async def test_not_configured_without_host_or_sender() -> None:
    config = Settings(_env_file=None)
    none = await resolve_smtp(_Store(), config, _Settings(""))  # type: ignore[arg-type]
    assert none.settings_source == "none"
    assert none.connection is None
    no_sender = await resolve_smtp(_Store(), config, _Settings("db.example", ""))  # type: ignore[arg-type]
    assert no_sender.connection is None


async def test_settings_db_failure_falls_back_to_env() -> None:
    class Broken:
        async def get(self) -> Any:
            raise RuntimeError("db down")

    config = Settings(_env_file=None, smtp_host="env.example", smtp_from_email="e@x.com")
    resolved = await resolve_smtp(_Store(), config, Broken())  # type: ignore[arg-type]
    assert (resolved.host, resolved.settings_source) == ("env.example", "env")
