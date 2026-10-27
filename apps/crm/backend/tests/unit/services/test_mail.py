"""`MailService` (M3-CRM-08): журнал, статусы, очередь, фейковый SMTP; без коннектора — 409.

Сессии подменены памятью: строки `email_log` живут в словаре, без Postgres.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.errors import ConflictError, Reason
from app.integrations.smtp import SmtpCheck, SmtpConnection, SmtpProbeError
from app.models.email import EmailLog
from app.schemas.settings import AppSettings
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services.mail import MailService

CIPHER = SecretCipher("k" * 40)
CONTEXT = {
    "full_name": "Азиз",
    "email": "aziz@railtech.uz",
    "temporary_password": "Tmp-pass-4321",
    "platform_url": "https://platform.example.com",
    "company": "RailTech",
}


class MemoryDb:
    def __init__(self) -> None:
        self.rows: dict[int, EmailLog] = {}

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator["MemorySession"]:
        yield MemorySession(self)


class MemorySession:
    def __init__(self, db: MemoryDb) -> None:
        self._db = db

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    def add(self, row: EmailLog) -> None:
        row.id = len(self._db.rows) + 1
        self._db.rows[row.id] = row

    async def flush(self) -> None:
        return None

    async def refresh(self, row: EmailLog) -> None:
        row.created_at = datetime.now(UTC)
        row.attempts = row.attempts or 0

    async def get(self, _model: type[EmailLog], row_id: int) -> EmailLog | None:
        return self._db.rows.get(row_id)

    async def scalars(self, _stmt: Any) -> Any:
        rows = sorted(self._db.rows.values(), key=lambda r: r.id, reverse=True)
        return type("Result", (), {"all": staticmethod(lambda: rows)})()


class FakeStore(SecretsStore):
    def __init__(self) -> None:
        super().__init__(None, CIPHER)  # type: ignore[arg-type]

    async def get(self, key: str) -> str | None:
        return None


class FakeSettings:
    def __init__(self, host: str) -> None:
        self.host = host

    async def get(self) -> AppSettings:
        return AppSettings.model_validate(
            {"integrations": {"smtp": {"host": self.host, "from_email": "crm@example.com"}}}
        )


class FakeTransport:
    def __init__(self, fail: SmtpProbeError | None = None) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        return SmtpCheck("fake", True, 1)

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((to, subject, body))


def build(
    host: str = "smtp.example.com",
    *,
    transport: FakeTransport | None = None,
    cipher: SecretCipher | None = CIPHER,
    enqueue_error: Exception | None = None,
    paused: list[bool] | None = None,
) -> tuple[MailService, MemoryDb, FakeTransport, list[int]]:
    db = MemoryDb()
    queued: list[int] = []
    transport = transport or FakeTransport()

    async def enqueue(email_log_id: int) -> int:
        if enqueue_error is not None:
            raise enqueue_error
        queued.append(email_log_id)
        return email_log_id

    service = MailService(
        db,  # type: ignore[arg-type]
        FakeStore(),
        cipher,
        Settings(_env_file=None),
        FakeSettings(host),  # type: ignore[arg-type]
        transport,
        enqueue,
        paused=_flag(paused if paused is not None else [False]),
    )
    return service, db, transport, queued


def _flag(state: list[bool]) -> Any:
    async def paused() -> bool:
        return state[0]

    return paused


async def test_send_queues_encrypted_body_and_delivery_marks_sent() -> None:
    service, db, transport, queued = build()
    view = await service.send(
        "invite", "Aziz@RailTech.uz", CONTEXT, user_id=7, requested_by=1, lang="en"
    )
    assert (view.status, view.to_email, view.lang) == ("queued", "aziz@railtech.uz", "en")
    assert queued == [view.id]
    row = db.rows[view.id]
    assert row.body_ciphertext is not None
    assert CONTEXT["temporary_password"].encode() not in row.body_ciphertext
    assert CONTEXT["temporary_password"] not in row.subject

    assert await service.deliver(view.id) is True
    (to, subject, body) = transport.sent[0]
    assert (to, subject) == ("aziz@railtech.uz", row.subject)
    assert CONTEXT["temporary_password"] in body
    assert (row.status, row.attempts) == ("sent", 1)
    assert row.body_ciphertext is None
    assert row.sent_at is not None
    # Повторная доставка той же строки — no-op.
    assert await service.deliver(view.id) is False
    assert len(transport.sent) == 1


async def test_without_smtp_logs_skipped_and_raises_clear_error() -> None:
    service, db, _, queued = build(host="")
    with capture_logs() as logs, pytest.raises(ConflictError) as info:
        await service.send("invite", "aziz@railtech.uz", CONTEXT, user_id=7)
    assert info.value.details["reason"] == Reason.SMTP_NOT_CONFIGURED.value
    assert queued == []
    (row,) = db.rows.values()
    assert (row.status, row.error, row.body_ciphertext) == (
        "skipped_no_smtp",
        "smtp_not_configured",
        None,
    )
    assert any(log["event"] == "email_skipped_no_smtp" for log in logs)
    assert not await service.configured()


async def test_without_secrets_key_body_cannot_be_stored() -> None:
    service, db, _, _ = build(cipher=None)
    with pytest.raises(ConflictError) as info:
        await service.send("invite", "aziz@railtech.uz", CONTEXT)
    assert info.value.details["reason"] == Reason.SECRETS_KEY_MISSING.value
    assert next(iter(db.rows.values())).status == "skipped_no_smtp"
    with pytest.raises(ConflictError):
        await service.ensure_configured()


async def test_failed_delivery_retries_then_gives_up_and_wipes_body() -> None:
    transport = FakeTransport(fail=SmtpProbeError("auth_failed", "SMTP 535"))
    service, db, _, _ = build(transport=transport)
    view = await service.send("password_reset", "aziz@railtech.uz", CONTEXT)
    row = db.rows[view.id]
    for attempt in (1, 2):
        with pytest.raises(SmtpProbeError):
            await service.deliver(view.id)
        assert (row.status, row.attempts, row.error) == ("failed", attempt, "auth_failed: SMTP 535")
        assert row.body_ciphertext is not None  # ещё будут попытки — тело нужно
        row.status = "queued"  # так делает повтор задачи: строка снова в работе
    assert await service.deliver(view.id) is False  # последняя попытка не бросает
    assert (row.status, row.attempts, row.body_ciphertext) == ("failed", 3, None)
    # Релей починили → письмо уходит, если строку вернуть в очередь.
    transport.fail = None
    row.status = "queued"
    assert await service.deliver(view.id) is False  # тела больше нет: не отправить
    assert (row.status, row.error) == ("failed", "body_expired")


async def test_enqueue_failure_is_recorded_not_lost() -> None:
    service, db, _, _ = build(enqueue_error=RuntimeError("queue down"))
    with pytest.raises(RuntimeError):
        await service.send("invite", "aziz@railtech.uz", CONTEXT)
    (row,) = db.rows.values()
    assert (row.status, row.error, row.body_ciphertext) == ("failed", "queue: RuntimeError", None)


async def test_log_lists_latest_first_without_bodies() -> None:
    service, _, _, _ = build()
    first = await service.send("invite", "a@railtech.uz", CONTEXT)
    second = await service.send("password_reset", "b@railtech.uz", CONTEXT)
    views = await service.list_log()
    assert [v.id for v in views] == [second.id, first.id]
    assert all(not hasattr(v, "body_ciphertext") for v in views)


async def test_paused_mail_holds_letters_in_journal_until_enabled() -> None:
    """Выключатель «Почта» (ADR-0024): письмо в журнале `queued`, воркер его не отправляет."""
    state = [True]
    service, db, transport, queued = build(paused=state)
    view = await service.send("invite", "aziz@railtech.uz", CONTEXT, user_id=7)
    assert view.status == "queued"
    assert queued == []
    assert db.rows[view.id].body_ciphertext is not None
    assert await service.deliver(view.id) is False
    assert transport.sent == []
    assert db.rows[view.id].attempts == 0

    state[0] = False
    assert await service.deliver(view.id) is True
    assert db.rows[view.id].status == "sent"
