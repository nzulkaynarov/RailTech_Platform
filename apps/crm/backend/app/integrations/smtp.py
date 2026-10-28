"""Коннектор «Почта» (M3-CRM-08, ADR-0018): настройки, секреты и транспорт SMTP.

Порядок чтения — как у ERP: запись из «Подключений» (несекретное — `settings.integrations.smtp`,
логин и пароль — `integration_secrets`), иначе `.env` (`SMTP_*`). Коннектор «настроен» = есть
хост и адрес отправителя; логин без пароля — ошибка настройки, релей без логина допустим.
Транспорт — `smtplib` из стандартной библиотеки в отдельном потоке (`asyncio.to_thread`):
отдельной зависимости нет, границу легко подменить в тестах. Значения секретов не логируются.
"""

import asyncio
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Literal, Protocol

import structlog

from app.config import Settings
from app.domain.smtp import Security, format_sender, host_problem, normalize_host
from app.security.secrets_store import SMTP_PASSWORD, SMTP_USERNAME, SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

Source = Literal["db", "env", "none"]
SmtpErrorKind = Literal["invalid_host", "unavailable", "auth_failed", "tls_failed", "rejected"]
TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class SmtpConnection:
    host: str
    port: int
    security: Security
    username: str
    password: str
    from_email: str
    from_name: str

    @property
    def sender(self) -> str:
        return format_sender(self.from_email, self.from_name)


@dataclass(frozen=True, slots=True)
class SmtpResolution:
    """Откуда взяты настройки (для «Подключений»); пароль — только в процессе."""

    host: str
    port: int
    security: Security
    from_email: str
    from_name: str
    settings_source: Source
    username: str
    username_source: Source
    password: str
    password_source: Source

    @property
    def connection(self) -> SmtpConnection | None:
        if not self.host or not self.from_email:
            return None
        return SmtpConnection(
            host=self.host,
            port=self.port,
            security=self.security,
            username=self.username,
            password=self.password,
            from_email=self.from_email,
            from_name=self.from_name,
        )


async def _stored(store: SecretsStore, key: str) -> str:
    if not store.enabled:
        return ""
    try:
        return await store.get(key) or ""
    except Exception:
        logger.warning("smtp_secret_db_unavailable", key=key, exc_info=True)
        return ""


def _pick(db_value: str, env_value: str) -> tuple[str, Source]:
    if db_value:
        return db_value, "db"
    return (env_value, "env") if env_value else ("", "none")


async def resolve_smtp(
    store: SecretsStore, config: Settings, settings: SettingsService | None = None
) -> SmtpResolution:
    """Настройки и секреты с источниками: БД («Подключения») → env; сбой БД → env."""
    stored = None
    if settings is not None:
        try:
            stored = (await settings.get()).integrations.smtp
        except Exception:
            logger.warning("smtp_settings_db_unavailable", exc_info=True)
    source: Source
    if stored is not None and normalize_host(stored.host):
        host, port, security = normalize_host(stored.host), stored.port, stored.security
        from_email, from_name, source = stored.from_email.strip(), stored.from_name.strip(), "db"
    else:
        host, port, security = (
            normalize_host(config.smtp_host),
            config.smtp_port,
            config.smtp_security,
        )
        from_email, from_name = config.smtp_from_email.strip(), config.smtp_from_name.strip()
        source = "env" if host else "none"
    username, username_source = _pick(await _stored(store, SMTP_USERNAME), config.smtp_username)
    password, password_source = _pick(
        await _stored(store, SMTP_PASSWORD), config.smtp_password.get_secret_value()
    )
    return SmtpResolution(
        host=host,
        port=port,
        security=security,
        from_email=from_email,
        from_name=from_name,
        settings_source=source,
        username=username,
        username_source=username_source,
        password=password,
        password_source=password_source,
    )


class SmtpProbeError(Exception):
    """Соединение/отправка не удались; `kind` — стабильный класс причины, `detail` — для экрана.

    `permanent` — повтор не поможет (сервер ответил 5xx на адрес, отправителя или данные письма):
    письмо сразу получает итог «ошибка». Остальное (сеть, TLS, вход, 4xx) — временное, повтор.
    """

    def __init__(self, kind: SmtpErrorKind, detail: str = "", *, permanent: bool = False) -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: SmtpErrorKind = kind
        self.detail = detail
        self.permanent = permanent


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """Вложение письма, уже скачанное из хранилища отправителя (W18A-P1)."""

    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class SmtpCheck:
    """Итог «Проверить связь»: приветствие сервера, вход выполнен ли, время ответа."""

    server: str
    authenticated: bool
    latency_ms: int


class SmtpTransport(Protocol):
    async def check(self, connection: SmtpConnection) -> SmtpCheck: ...

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        """Простое письмо: `to` — адрес или несколько через запятую.

        Письмо с HTML, ответом на другой адрес или вложениями (запросы ERP и EDS, W18A-P1) —
        тот же метод с ключевыми `html`, `reply_to`, `attachments`; транспорт `SmtplibTransport`
        их принимает.
        """
        ...


def build_message(
    connection: SmtpConnection,
    to: str,
    subject: str,
    body: str,
    *,
    html: str | None = None,
    reply_to: str | None = None,
    attachments: tuple[MailAttachment, ...] = (),
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = connection.sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain=connection.from_email.rpartition("@")[2] or None)
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body, charset="utf-8")
    if html:
        message.add_alternative(html, subtype="html", charset="utf-8")
    for item in attachments:
        maintype, _, subtype = item.content_type.partition("/")
        message.add_attachment(
            item.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=item.filename,
        )
    return message


class SmtplibTransport:
    """`smtplib` в потоке: EHLO → STARTTLS/SMTPS → AUTH (если есть логин) → QUIT или отправка."""

    def __init__(self, timeout_s: float = TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        return await asyncio.to_thread(self._check, connection)

    async def send(
        self,
        connection: SmtpConnection,
        to: str,
        subject: str,
        body: str,
        *,
        html: str | None = None,
        reply_to: str | None = None,
        attachments: tuple[MailAttachment, ...] = (),
    ) -> None:
        message = build_message(
            connection, to, subject, body, html=html, reply_to=reply_to, attachments=attachments
        )
        await asyncio.to_thread(self._send, connection, message)

    def _check(self, connection: SmtpConnection) -> SmtpCheck:
        started = time.monotonic()
        with self._session(connection) as client:
            server = _ehlo_name(client)
            authenticated = self._login(client, connection)
        return SmtpCheck(server, authenticated, int((time.monotonic() - started) * 1000))

    def _send(self, connection: SmtpConnection, message: EmailMessage) -> None:
        with self._session(connection) as client:
            self._login(client, connection)
            try:
                client.send_message(message)
            except smtplib.SMTPRecipientsRefused as exc:
                permanent = all(code >= 500 for code, _ in exc.recipients.values())
                raise SmtpProbeError(
                    "rejected", _codes(exc.recipients), permanent=permanent
                ) from exc
            except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
                raise SmtpProbeError(
                    "rejected", f"SMTP {exc.smtp_code}", permanent=exc.smtp_code >= 500
                ) from exc
            except smtplib.SMTPException as exc:
                raise SmtpProbeError("unavailable", type(exc).__name__) from exc

    def _session(self, connection: SmtpConnection) -> smtplib.SMTP:
        problem = host_problem(connection.host)
        if problem is not None:
            raise SmtpProbeError("invalid_host", problem)
        try:
            if connection.security == "ssl":
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    connection.host,
                    connection.port,
                    timeout=self._timeout_s,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(connection.host, connection.port, timeout=self._timeout_s)
            client.ehlo()
            if connection.security == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
        except ssl.SSLError as exc:
            raise SmtpProbeError("tls_failed", exc.reason or type(exc).__name__) from exc
        except smtplib.SMTPNotSupportedError as exc:
            raise SmtpProbeError("tls_failed", "STARTTLS not supported") from exc
        except (TimeoutError, socket.gaierror, ConnectionError, OSError) as exc:
            raise SmtpProbeError("unavailable", type(exc).__name__) from exc
        except smtplib.SMTPException as exc:
            raise SmtpProbeError("unavailable", type(exc).__name__) from exc
        return client

    @staticmethod
    def _login(client: smtplib.SMTP, connection: SmtpConnection) -> bool:
        if not connection.username:
            return False
        try:
            client.login(connection.username, connection.password)
        except smtplib.SMTPAuthenticationError as exc:
            raise SmtpProbeError("auth_failed", f"SMTP {exc.smtp_code}") from exc
        except smtplib.SMTPNotSupportedError as exc:
            raise SmtpProbeError("auth_failed", "AUTH not supported") from exc
        except smtplib.SMTPException as exc:
            raise SmtpProbeError("unavailable", type(exc).__name__) from exc
        return True


def _ehlo_name(client: smtplib.SMTP) -> str:
    raw = client.ehlo_resp or b""
    first = raw.decode("utf-8", errors="replace").splitlines()[:1]
    return first[0][:120] if first else ""


def _codes(recipients: dict[str, tuple[int, bytes]]) -> str:
    return ", ".join(f"{address}: SMTP {code}" for address, (code, _) in recipients.items())[:200]
