"""Общий ящик входящей почты (W18A-P2, B-INB-5): настройки, секреты и транспорт IMAP.

Настройки — только из «Подключений» (DECISIONS 2026-10-28, «настройка только через интерфейс»):
несекретное — `settings.integrations.imap`, логин и пароль приложения — `integration_secrets`.
Транспорт — `imaplib` стандартной библиотеки в потоке (`asyncio.to_thread`): папка открывается
только на чтение (`EXAMINE`), письма читаются `BODY.PEEK[]` — на сервере ничего не удаляется и не
помечается прочитанным. Что уже забрано, CRM помнит у себя: UIDVALIDITY и последний UID каждой
папки. Папок может быть несколько (W18A-P2-2: «Входящие» и «Спам»); «Найти папки» — `LIST`,
загрузка истории — `UID SEARCH SINCE` и чтение выбранных UID. Значения секретов не логируются.
"""

import asyncio
import contextlib
import imaplib
import re
import socket
import ssl
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol

import structlog

from app.domain.inbound_folders import FolderSetting, ServerFolder, parse_list, resolve_folders
from app.domain.smtp import host_problem, normalize_host
from app.security.secrets_store import IMAP_PASSWORD, IMAP_USERNAME, SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

ImapErrorKind = Literal[
    "invalid_host", "unavailable", "auth_failed", "tls_failed", "mailbox_missing"
]
ImapSecurity = Literal["ssl", "starttls"]
TIMEOUT_S: Final = 20.0
#: Писем за один опрос (остальные — следующим опросом, по возрастанию UID).
BATCH: Final = 25
#: Первый опрос (или смена UIDVALIDITY): письма за последние дни, не вся история ящика.
FIRST_POLL_DAYS: Final = 3
#: Письмо больше этого не скачивается целиком: в очередь — заголовки и пометка «слишком большое».
MAX_MESSAGE_BYTES: Final = 60 * 1024 * 1024
_UIDVALIDITY: Final = re.compile(rb"UIDVALIDITY (\d+)")
_SIZE: Final = re.compile(rb"UID (\d+) RFC822\.SIZE (\d+)|RFC822\.SIZE (\d+) UID (\d+)")


@dataclass(frozen=True, slots=True)
class ImapConnection:
    host: str
    port: int
    security: ImapSecurity
    mailbox: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class ImapResolution:
    host: str
    port: int
    security: ImapSecurity
    mailbox: str
    username: str
    password: str
    folders: tuple[FolderSetting, ...] = ()

    @property
    def connection(self) -> ImapConnection | None:
        if not self.host or not self.username or not self.password:
            return None
        return ImapConnection(
            self.host, self.port, self.security, self.mailbox, self.username, self.password
        )


async def _stored(store: SecretsStore, key: str) -> str:
    if not store.enabled:
        return ""
    try:
        return await store.get(key) or ""
    except Exception:
        logger.warning("imap_secret_db_unavailable", key=key, exc_info=True)
        return ""


async def resolve_imap(store: SecretsStore, settings: SettingsService) -> ImapResolution:
    stored = (await settings.get()).integrations.imap
    folders = resolve_folders(
        [FolderSetting(f.name, f.spam) for f in stored.folders], stored.mailbox
    )
    return ImapResolution(
        host=normalize_host(stored.host.removeprefix("imap://").removeprefix("imaps://")),
        port=stored.port,
        security=stored.security,
        mailbox=stored.mailbox.strip() or "INBOX",
        username=(await _stored(store, IMAP_USERNAME)).strip(),
        password=await _stored(store, IMAP_PASSWORD),
        folders=folders,
    )


def in_folder(connection: ImapConnection, folder: str) -> ImapConnection:
    """То же соединение, другая папка."""
    return replace(connection, mailbox=folder)


class ImapProbeError(Exception):
    def __init__(self, kind: ImapErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: ImapErrorKind = kind
        self.detail = detail[:200]


@dataclass(frozen=True, slots=True)
class ImapCheck:
    messages: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class FetchedMessage:
    uid: int
    raw: bytes
    too_large: bool = False


@dataclass(frozen=True, slots=True)
class FetchBatch:
    uidvalidity: int
    messages: tuple[FetchedMessage, ...]


class ImapClient(Protocol):
    async def check(self, connection: ImapConnection) -> ImapCheck: ...

    async def fetch(
        self, connection: ImapConnection, uidvalidity: int | None, last_uid: int | None
    ) -> FetchBatch: ...

    async def folders(self, connection: ImapConnection) -> list[ServerFolder]: ...

    async def search_since(
        self, connection: ImapConnection, days: int
    ) -> tuple[int, list[int]]: ...

    async def fetch_uids(
        self, connection: ImapConnection, uids: Sequence[int]
    ) -> tuple[FetchedMessage, ...]: ...


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ImaplibClient:
    """`imaplib` в потоке: TLS → LOGIN → EXAMINE (только чтение) → UID SEARCH/FETCH → LOGOUT."""

    def __init__(self, timeout_s: float = TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    async def check(self, connection: ImapConnection) -> ImapCheck:
        return await asyncio.to_thread(self._check, connection)

    async def fetch(
        self, connection: ImapConnection, uidvalidity: int | None, last_uid: int | None
    ) -> FetchBatch:
        return await asyncio.to_thread(self._fetch, connection, uidvalidity, last_uid)

    async def folders(self, connection: ImapConnection) -> list[ServerFolder]:
        return await asyncio.to_thread(self._folders, connection)

    async def search_since(self, connection: ImapConnection, days: int) -> tuple[int, list[int]]:
        """Папка `connection.mailbox`: (UIDVALIDITY, UID писем за последние `days` дней)."""
        return await asyncio.to_thread(self._search_since, connection, days)

    async def fetch_uids(
        self, connection: ImapConnection, uids: Sequence[int]
    ) -> tuple[FetchedMessage, ...]:
        """Письма с этими UID папки `connection.mailbox` (только чтение, `BODY.PEEK`)."""
        return await asyncio.to_thread(self._fetch_uids, connection, list(uids))

    def _folders(self, connection: ImapConnection) -> list[ServerFolder]:
        client = self._session(connection)
        try:
            status, data = client.list()
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("unavailable", str(exc)[:200]) from exc
        except (TimeoutError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        finally:
            _logout(client)
        if status != "OK":
            raise ImapProbeError("unavailable", "LIST")
        lines: list[bytes | tuple[bytes, bytes]] = []
        for item in data:
            if isinstance(item, bytes):
                lines.append(item)
            elif isinstance(item, tuple) and len(item) > 1:
                lines.append((bytes(item[0]), bytes(item[1])))
        return parse_list(lines)

    def _search_since(self, connection: ImapConnection, days: int) -> tuple[int, list[int]]:
        client = self._session(connection)
        try:
            _, current = self._examine(client, connection.mailbox)
            return current, _search(client, None, days=days)
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("unavailable", str(exc)[:200]) from exc
        except (TimeoutError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        finally:
            _logout(client)

    def _fetch_uids(
        self, connection: ImapConnection, uids: list[int]
    ) -> tuple[FetchedMessage, ...]:
        client = self._session(connection)
        try:
            self._examine(client, connection.mailbox)
            sizes = _sizes(client, uids)
            # письмо удалили между поиском и чтением — его просто нет
            return tuple(_one(client, uid, sizes[uid]) for uid in uids if uid in sizes)
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("unavailable", str(exc)[:200]) from exc
        except (TimeoutError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        finally:
            _logout(client)

    def _check(self, connection: ImapConnection) -> ImapCheck:
        started = time.monotonic()
        client = self._session(connection)
        try:
            count, _ = self._examine(client, connection.mailbox)
        finally:
            _logout(client)
        return ImapCheck(count, int((time.monotonic() - started) * 1000))

    def _fetch(
        self, connection: ImapConnection, uidvalidity: int | None, last_uid: int | None
    ) -> FetchBatch:
        client = self._session(connection)
        try:
            _, current = self._examine(client, connection.mailbox)
            resume = uidvalidity == current and last_uid is not None
            uids = _search(client, last_uid if resume else None)
            if resume and last_uid is not None:
                uids = [uid for uid in uids if uid > last_uid]
            chosen = sorted(uids)[:BATCH]
            sizes = _sizes(client, chosen)
            messages = tuple(_one(client, uid, sizes.get(uid, 0)) for uid in chosen)
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("unavailable", str(exc)[:200]) from exc
        except (TimeoutError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        finally:
            _logout(client)
        return FetchBatch(current, messages)

    def _open(self, connection: ImapConnection) -> imaplib.IMAP4:
        """Соединение с TLS (IMAPS или STARTTLS); тесты подменяют на сокет фейкового сервера."""
        context = ssl.create_default_context()
        if connection.security == "ssl":
            return imaplib.IMAP4_SSL(
                connection.host, connection.port, ssl_context=context, timeout=self._timeout_s
            )
        client = imaplib.IMAP4(connection.host, connection.port, timeout=self._timeout_s)
        client.starttls(ssl_context=context)
        return client

    def _session(self, connection: ImapConnection) -> imaplib.IMAP4:
        problem = host_problem(connection.host)
        if problem is not None:
            raise ImapProbeError("invalid_host", problem)
        try:
            client = self._open(connection)
        except ssl.SSLError as exc:
            raise ImapProbeError("tls_failed", exc.reason or type(exc).__name__) from exc
        except imaplib.IMAP4.abort as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("tls_failed", "STARTTLS not supported") from exc
        except (TimeoutError, socket.gaierror, ConnectionError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        try:
            client.login(connection.username, connection.password)
        except imaplib.IMAP4.error as exc:
            _logout(client)
            raise ImapProbeError("auth_failed", "LOGIN rejected") from exc
        except (TimeoutError, OSError) as exc:
            raise ImapProbeError("unavailable", type(exc).__name__) from exc
        return client

    @staticmethod
    def _examine(client: imaplib.IMAP4, mailbox: str) -> tuple[int, int]:
        """Папка только на чтение: (число писем, UIDVALIDITY)."""
        try:
            status, data = client.select(_quote(mailbox), readonly=True)
        except imaplib.IMAP4.error as exc:
            raise ImapProbeError("mailbox_missing", mailbox) from exc
        if status != "OK":
            raise ImapProbeError("mailbox_missing", mailbox)
        count = int(data[0]) if data and data[0] and bytes(data[0]).isdigit() else 0
        _, codes = client.response("UIDVALIDITY")
        raw = codes[0] if codes and codes[0] else b"0"
        match = _UIDVALIDITY.search(b"UIDVALIDITY " + bytes(raw))
        return count, int(match.group(1)) if match else 0


def _search(
    client: imaplib.IMAP4, last_uid: int | None, *, days: int = FIRST_POLL_DAYS
) -> list[int]:
    if last_uid is not None:
        status, data = client.uid("SEARCH", f"UID {last_uid + 1}:*")
    else:
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = client.uid("SEARCH", f"SINCE {since}")
    if status != "OK" or not data or not data[0]:
        return []
    return [int(item) for item in bytes(data[0]).split() if item.isdigit()]


def _sizes(client: imaplib.IMAP4, uids: list[int]) -> dict[int, int]:
    if not uids:
        return {}
    status, data = client.uid("FETCH", ",".join(map(str, uids)), "(RFC822.SIZE)")
    sizes: dict[int, int] = {}
    if status != "OK":
        return sizes
    for item in data:
        line = item[0] if isinstance(item, tuple) else item
        if not isinstance(line, bytes):
            continue
        match = _SIZE.search(line)
        if match:
            uid, size = (
                (match.group(1), match.group(2))
                if match.group(1)
                else (
                    match.group(4),
                    match.group(3),
                )
            )
            sizes[int(uid)] = int(size)
    return sizes


def _one(client: imaplib.IMAP4, uid: int, size: int) -> FetchedMessage:
    too_large = size > MAX_MESSAGE_BYTES
    part = "(BODY.PEEK[HEADER])" if too_large else "(BODY.PEEK[])"
    status, data = client.uid("FETCH", str(uid), part)
    if status != "OK":
        raise ImapProbeError("unavailable", f"FETCH {uid}")
    raw = b"".join(bytes(item[1]) for item in data if isinstance(item, tuple) and len(item) > 1)
    return FetchedMessage(uid, raw, too_large)


def _logout(client: imaplib.IMAP4) -> None:
    with contextlib.suppress(Exception):  # соединение и так закрывается
        client.logout()
