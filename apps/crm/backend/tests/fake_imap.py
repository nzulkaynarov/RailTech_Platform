"""Фейковый IMAP-сервер для тестов входящей почты (W18A-P2): без внешних сервисов и TLS.

Понимает ровно то, что шлёт `app/integrations/imap.ImaplibClient`: CAPABILITY, LOGIN, LIST,
SELECT/EXAMINE, UID SEARCH (`UID n:*`, `SINCE …` — по дате поступления письма), UID FETCH
(`RFC822.SIZE`, `BODY.PEEK[]`, `BODY.PEEK[HEADER]`), LOGOUT. Папки: `server.box` — INBOX,
`server.folder(name, flags)` — ещё одна (например «Spam» с флагом `\\Junk`, W18A-P2-2).
Запоминает, открывалась ли папка на запись и были ли команды, меняющие ящик (STORE, EXPUNGE, COPY…),
чтобы тест проверил: на сервере ничего не удаляется и не помечается.
"""

import imaplib
import re
import socketserver
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import TracebackType

from app.integrations.imap import ImapConnection, ImaplibClient

USERNAME = "inbox@company.test"
PASSWORD = "app-password-for-tests"


@dataclass
class Mailbox:
    uidvalidity: int = 1001
    messages: dict[int, bytes] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    selected_readwrite: bool = False
    logins: int = 0
    flags: str = "\\HasNoChildren"
    dates: dict[int, date] = field(default_factory=dict)

    def add(self, uid: int, raw: bytes, received: datetime | None = None) -> None:
        self.messages[uid] = raw
        self.dates[uid] = (received or datetime.now(UTC)).date()


_SEQ = re.compile(r"^(\d+)(?::(\*|\d+))?$")


class _Handler(socketserver.StreamRequestHandler):
    server: "_Server"
    selected: Mailbox | None = None

    def _send(self, line: str | bytes) -> None:
        data = line if isinstance(line, bytes) else line.encode()
        self.wfile.write(data + b"\r\n")

    def handle(self) -> None:
        box = self.server.box
        self._send("* OK fake IMAP ready")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            tag, _, rest = raw.decode().rstrip("\r\n").partition(" ")
            command, _, args = rest.partition(" ")
            command = command.upper()
            if command == "CAPABILITY":
                self._send("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
                self._send(f"{tag} OK done")
            elif command == "LOGIN":
                user, _, password = args.partition(" ")
                if user.strip('"') == USERNAME and password.strip('"') == PASSWORD:
                    box.logins += 1
                    self._send(f"{tag} OK logged in")
                else:
                    self._send(f"{tag} NO [AUTHENTICATIONFAILED] invalid credentials")
            elif command == "LIST":
                for name, folder in self.server.folders.items():
                    self._send(f'* LIST ({folder.flags}) "/" "{name}"')
                self._send(f"{tag} OK list done")
            elif command in ("SELECT", "EXAMINE"):
                found = self.server.folders.get(args.strip('"'))
                if found is None:
                    self._send(f"{tag} NO no such mailbox")
                    continue
                box.selected_readwrite = box.selected_readwrite or command == "SELECT"
                self.selected = found
                self._send(f"* {len(found.messages)} EXISTS")
                self._send(f"* OK [UIDVALIDITY {found.uidvalidity}] UIDs valid")
                mode = "READ-ONLY" if command == "EXAMINE" else "READ-WRITE"
                self._send(f"{tag} OK [{mode}] done")
            elif command == "UID":
                self._uid(tag, args)
            elif command == "LOGOUT":
                self._send("* BYE")
                self._send(f"{tag} OK bye")
                return
            else:
                box.writes.append(command)
                self._send(f"{tag} OK ignored")

    def _uids(self, spec: str) -> list[int]:
        box = self.selected or self.server.box
        out: list[int] = []
        for chunk in spec.split(","):
            match = _SEQ.match(chunk)
            if not match:
                continue
            low = int(match.group(1))
            high_raw = match.group(2)
            if high_raw is None:
                out += [low] if low in box.messages else []
                continue
            high = max(box.messages, default=0) if high_raw == "*" else int(high_raw)
            found = [uid for uid in sorted(box.messages) if min(low, high) <= uid <= max(low, high)]
            # RFC 3501: «n:*» при n > последнего UID всё равно отдаёт последнее письмо.
            if not found and high_raw == "*" and box.messages:
                found = [max(box.messages)]
            out += found
        return out

    def _uid(self, tag: str, args: str) -> None:
        box = self.selected or self.server.box
        sub, _, rest = args.partition(" ")
        sub = sub.upper()
        if sub == "SEARCH":
            if rest.upper().startswith("UID "):
                uids = self._uids(rest[4:].strip())
            elif rest.upper().startswith("SINCE "):
                since = datetime.strptime(rest[6:].strip(), "%d-%b-%Y").date()
                uids = [uid for uid in sorted(box.messages) if box.dates.get(uid, since) >= since]
            else:
                uids = sorted(box.messages)
            self._send("* SEARCH " + " ".join(map(str, uids)))
            self._send(f"{tag} OK search done")
        elif sub == "FETCH":
            spec, _, what = rest.partition(" ")
            for uid in self._uids(spec):
                raw = box.messages[uid]
                if "RFC822.SIZE" in what:
                    self._send(f"* {uid} FETCH (UID {uid} RFC822.SIZE {len(raw)})")
                    continue
                body = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n" if "HEADER" in what else raw
                section = "BODY[HEADER]" if "HEADER" in what else "BODY[]"
                self._send(f"* {uid} FETCH (UID {uid} {section} {{{len(body)}}}".encode())
                self.wfile.write(body)
                self._send(")")
            self._send(f"{tag} OK fetch done")
        else:
            box.writes.append(f"UID {sub}")
            self._send(f"{tag} OK ignored")


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, box: Mailbox) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.box = box
        self.folders: dict[str, Mailbox] = {"INBOX": box}


class FakeImapServer:
    """Контекст: `with FakeImapServer() as server: server.port, server.box`."""

    def __init__(self, box: Mailbox | None = None) -> None:
        self.box = box or Mailbox()
        self._server = _Server(self.box)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def folder(self, name: str, flags: str = "\\HasNoChildren", uidvalidity: int = 2001) -> Mailbox:
        """Ещё одна папка ящика (`flags` — как в ответе LIST, например `\\HasNoChildren \\Junk`)."""
        box = Mailbox(uidvalidity=uidvalidity, flags=flags)
        self._server.folders[name] = box
        return box

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self) -> "FakeImapServer":
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()


class PlainClient(ImaplibClient):
    """Настоящий клиент без TLS: фейковый сервер слушает простой сокет."""

    def _open(self, connection: ImapConnection) -> imaplib.IMAP4:
        return imaplib.IMAP4(connection.host, connection.port, timeout=5)
