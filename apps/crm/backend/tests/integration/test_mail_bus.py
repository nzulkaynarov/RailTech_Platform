"""Один отправитель ансамбля (W18A-P1, B-INB-6) на реальном Postgres: ERP и EDS просят письмо по
шине, CRM принимает запрос в журнал доставки, отправляет и возвращает итог событием.

Приём — настоящий приёмник `CrmBus` с подписью пары, обработка — `process_inbox` (задача очереди),
постановка письма — хук после коммита; SMTP и хранилище вложений — подставные.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.bus.runtime import CrmBus, build_bus
from app.config import Settings
from app.integrations.mail_attachments import AttachmentError, AttachmentRef
from app.integrations.smtp import MailAttachment, SmtpCheck, SmtpConnection, SmtpProbeError
from app.models.email import EmailLog
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services.mail import MailService
from app.services.mail_content import MailContent, MailLink, seal
from app.services.mail_requests import MailRequestService
from app.services.settings import SettingsService
from tests.bus_events import envelope_for, signed_request

pytestmark = pytest.mark.integration

PAIR_ERP = "mail-bus-test-pair-erp-crm-0001"  # фиктивные секреты пар
PAIR_EDS = "mail-bus-test-pair-eds-crm-0001"
SECRETS_KEY = "k" * 64
ERP_TYPE = "uz.railtech.erp.mail.requested.v1"
EDS_TYPE = "uz.railtech.eds.mail.requested.v1"
PDF = b"%PDF-1.7 quote 0142"
LINK = "http://rustfs:9000/erp-temp/mail/0142/quote.pdf?X-Amz-Signature=00"
MAGIC = "https://cabinet.example.com/auth/magic#token=one-time-token-value"


class FakeTransport:
    def __init__(self) -> None:
        self.errors: list[SmtpProbeError] = []
        self.sent: list[dict[str, Any]] = []

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        return SmtpCheck("relay.test", True, 1)

    async def send(
        self, connection: SmtpConnection, to: str, subject: str, body: str, **extra: Any
    ) -> None:
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append({"to": to, "subject": subject, "body": body, **extra})


class FakeFetcher:
    def __init__(self) -> None:
        self.error: AttachmentError | None = None
        self.fetched: list[AttachmentRef] = []

    async def fetch(self, ref: AttachmentRef) -> bytes:
        if self.error is not None:
            raise self.error
        self.fetched.append(ref)
        return PDF


class FakeContainer:
    def __init__(self, bus: CrmBus, requests: MailRequestService) -> None:
        self.bus = bus
        self.mail_requests = requests


class Stand:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, smtp: bool = True) -> None:
        self.sessions = sessions
        self.transport = FakeTransport()
        self.fetcher = FakeFetcher()
        self.queued: list[int] = []
        smtp_env = (
            {"smtp_host": "smtp.test", "smtp_from_email": "crm@railtech.test"} if smtp else {}
        )
        config = Settings(
            _env_file=None, app_env="test", secrets_key=SecretStr(SECRETS_KEY), **smtp_env
        )
        cipher = SecretCipher(SECRETS_KEY)
        self.mail = MailService(
            sessions,
            SecretsStore(sessions, cipher),
            cipher,
            config,
            SettingsService(sessions),
            self.transport,
            self._enqueue,
            fetcher=self.fetcher,
        )
        self.bus = build_bus(sessions, None, after_processed=self._after, enqueue=self._noop)
        self.requests = MailRequestService(sessions, self.mail, self.bus.config.secrets)
        from app.bus import handlers  # noqa: F401 — регистрирует обработчики

        runtime.install(cast(Any, FakeContainer(self.bus, self.requests)))

    async def _enqueue(self, email_log_id: int) -> int:
        self.queued.append(email_log_id)
        return email_log_id

    async def _noop(self, event_id: str) -> None:
        return None

    async def _after(self, event_id: str) -> None:
        await self.requests.dispatch(event_id)

    async def request(
        self,
        *,
        key: str = "erp:email_log:1",
        publisher: str = "erp",
        secret: str = PAIR_ERP,
        content: MailContent | None = None,
        attachments: bool = False,
        content_secret: str | None = None,
        **data: Any,
    ) -> str:
        links = (MailLink(LINK, "2026-10-29T09:00:00Z"),) if attachments else ()
        body = content or MailContent(f"Вход в кабинет: {MAGIC}", "<p>Вход</p>", links)
        payload: dict[str, Any] = {
            "request_key": key,
            "purpose": "portal_magic_link",
            "to": ["Buyer@Example.com"],
            "subject": "Вход в кабинет",
            "language": "ru",
            "ref": {"kind": "contact", "id": "310"},
            "notify": True,
            "content": {
                "alg": "fernet-pair-v1",
                "ciphertext": seal(content_secret or secret, body),
            },
            **data,
        }
        if attachments:
            payload["attachments"] = [
                {
                    "filename": "КП-0142.pdf",
                    "content_type": "application/pdf",
                    "size": len(PDF),
                    "sha256": hashlib.sha256(PDF).hexdigest(),
                }
            ]
        event_type = ERP_TYPE if publisher == "erp" else EDS_TYPE
        envelope = envelope_for(event_type, payload, source=f"rt://{publisher}")
        headers, raw = signed_request(envelope, secret, publisher=publisher)
        result = await self.bus.receive(headers, raw)
        assert result.status_code == 200, result.body
        status = await self.bus.process_inbox(envelope["id"])
        assert status == "processed", status
        return str(envelope["id"])

    async def rows(self) -> list[EmailLog]:
        async with self.sessions() as session:
            return list((await session.scalars(select(EmailLog).order_by(EmailLog.id))).all())

    async def outbox(self) -> list[tuple[str, dict[str, Any]]]:
        async with self.sessions() as session:
            found = await session.execute(
                text("SELECT type, envelope FROM rt_bus_outbox ORDER BY created_at, id")
            )
            return [(row.type, row.envelope["data"]) for row in found]


@pytest.fixture
async def stand(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stand]:
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", PAIR_ERP)
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR_EDS)
    built = Stand(sessions)
    yield built
    runtime.install(None)


async def test_erp_request_becomes_one_encrypted_journal_row_sent_after_commit(
    stand: Stand,
) -> None:
    await stand.request()
    (row,) = await stand.rows()
    assert (row.source, row.purpose, row.status) == ("erp", "portal_magic_link", "queued")
    assert (row.request_key, row.ref_kind, row.ref_id, row.notify) == (
        "erp:email_log:1",
        "contact",
        "310",
        True,
    )
    assert row.to_email == "buyer@example.com"
    # Ссылка входа не лежит открыто ни в журнале, ни в inbox.
    assert row.body_ciphertext is not None
    assert MAGIC.encode() not in row.body_ciphertext
    async with stand.sessions() as session:
        inbox = await session.scalar(text("SELECT envelope::text FROM rt_bus_inbox"))
    assert MAGIC not in str(inbox)
    assert stand.queued == [row.id], "письмо ставится в очередь после коммита обработки"

    assert await stand.mail.deliver(row.id) is True
    (sent,) = stand.transport.sent
    assert MAGIC in sent["body"]
    assert sent["html"] == "<p>Вход</p>"
    (row,) = await stand.rows()
    assert (row.status, row.body_ciphertext, row.html_ciphertext) == ("sent", None, None)
    ((event_type, data),) = await stand.outbox()
    assert event_type == "uz.railtech.crm.mail.sent.v1"
    assert data["requester"] == "erp"
    assert data["request_key"] == "erp:email_log:1"
    assert data["ref"] == {"kind": "contact", "id": "310"}
    assert "to" not in data
    assert "subject" not in data


async def test_repeated_request_with_the_same_key_gives_no_second_letter(stand: Stand) -> None:
    await stand.request(key="erp:email_log:7")
    await stand.request(key="erp:email_log:7")  # повторная публикация: новый id конверта
    await stand.request(key="erp:email_log:7", publisher="eds", secret=PAIR_EDS)  # чужой источник
    rows = await stand.rows()
    assert [(r.source, r.request_key) for r in rows] == [
        ("erp", "erp:email_log:7"),
        ("eds", "erp:email_log:7"),
    ]
    assert stand.queued == [rows[0].id, rows[1].id]


async def test_concurrent_requests_with_the_same_key_make_one_row(stand: Stand) -> None:
    """Два воркера обрабатывают два события с одним ключом одновременно: строка одна.

    Защита — UNIQUE (`source`, `request_key`) и точка сохранения: проверка «уже есть» обоих
    пропускает, вторая вставка ловит нарушение уникальности (мутационная проверка — в PR)."""
    payload_key = "erp:email_log:42"
    envelopes = []
    for _ in range(2):
        body = MailContent("текст", None, ())
        data = {
            "request_key": payload_key,
            "purpose": "invite",
            "to": ["a@example.com"],
            "subject": "Приглашение",
            "content": {"alg": "fernet-pair-v1", "ciphertext": seal(PAIR_ERP, body)},
        }
        envelopes.append(envelope_for(ERP_TYPE, data))
    from rt_bus import Event

    gate = asyncio.Barrier(2)
    original = MailRequestService._known

    async def known_then_wait(session: AsyncSession, source: str, key: str) -> bool:
        found = await original(session, source, key)
        await gate.wait()  # оба воркера прошли проверку до вставки
        return found

    async def accept(envelope: dict[str, Any]) -> int | None:
        async with stand.sessions() as session, session.begin():
            return await stand.requests.accept(session, Event.from_dict(envelope))

    stand.requests._known = known_then_wait  # type: ignore[method-assign]
    results = await asyncio.gather(*(accept(e) for e in envelopes))
    assert sorted(r is None for r in results) == [False, True]
    assert len(await stand.rows()) == 1


async def test_attachment_by_link_is_downloaded_checked_and_attached(stand: Stand) -> None:
    await stand.request(attachments=True)
    (row,) = await stand.rows()
    assert row.attachments == [
        {
            "filename": "КП-0142.pdf",
            "content_type": "application/pdf",
            "size": len(PDF),
            "sha256": hashlib.sha256(PDF).hexdigest(),
        }
    ]
    assert row.links_ciphertext is not None
    assert LINK.encode() not in row.links_ciphertext
    assert await stand.mail.deliver(row.id) is True
    (ref,) = stand.fetcher.fetched
    assert ref.url == LINK
    (sent,) = stand.transport.sent
    assert sent["attachments"] == (MailAttachment("КП-0142.pdf", "application/pdf", PDF),)
    (row,) = await stand.rows()
    assert row.links_ciphertext is None


async def test_unavailable_attachment_is_a_failed_result_with_reason(stand: Stand) -> None:
    await stand.request(attachments=True)
    stand.fetcher.error = AttachmentError(
        "attachment_unavailable", "КП-0142.pdf: HTTP 403", permanent=True
    )
    (row,) = await stand.rows()
    assert await stand.mail.deliver(row.id) is False
    (row,) = await stand.rows()
    assert (row.status, row.error) == ("failed", "attachment_unavailable: КП-0142.pdf: HTTP 403")
    ((event_type, data),) = await stand.outbox()
    assert event_type == "uz.railtech.crm.mail.failed.v1"
    assert (data["reason"], data["detail"]) == ("attachment_unavailable", "КП-0142.pdf: HTTP 403")


async def test_temporary_smtp_error_is_retried_and_then_sent(stand: Stand) -> None:
    await stand.request()
    (row,) = await stand.rows()
    stand.transport.errors = [SmtpProbeError("unavailable", "TimeoutError")]
    with pytest.raises(SmtpProbeError):
        await stand.mail.deliver(row.id)
    (row,) = await stand.rows()
    assert (row.status, row.attempts, row.error) == ("queued", 1, "unavailable: TimeoutError")
    assert await stand.outbox() == [], "итога ещё нет"
    assert await stand.mail.deliver(row.id) is True
    assert [t for t, _ in await stand.outbox()] == ["uz.railtech.crm.mail.sent.v1"]


async def test_permanent_rejection_is_failed_at_once_without_addresses_in_the_result(
    stand: Stand,
) -> None:
    await stand.request()
    (row,) = await stand.rows()
    stand.transport.errors = [
        SmtpProbeError("rejected", "buyer@example.com: SMTP 550", permanent=True)
    ]
    assert await stand.mail.deliver(row.id) is False
    (row,) = await stand.rows()
    assert (row.status, row.attempts, row.body_ciphertext) == ("failed", 1, None)
    ((event_type, data),) = await stand.outbox()
    assert event_type == "uz.railtech.crm.mail.failed.v1"
    assert data["reason"] == "rejected"
    assert "buyer@example.com" not in data["detail"]


async def test_unreadable_content_and_missing_smtp_fail_at_once(
    stand: Stand, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await stand.request(key="erp:email_log:5", content_secret="not-the-pair-secret")
    (row,) = await stand.rows()
    assert (row.status, row.error, row.body_ciphertext) == ("failed", "content_unreadable", None)
    assert stand.queued == []
    ((event_type, data),) = await stand.outbox()
    assert (event_type, data["reason"]) == ("uz.railtech.crm.mail.failed.v1", "content_unreadable")

    no_smtp = Stand(sessions, smtp=False)
    await no_smtp.request(key="erp:email_log:6")
    row = (await no_smtp.rows())[-1]
    assert (row.status, row.error) == ("skipped_no_smtp", "smtp_not_configured")
    assert (await no_smtp.outbox())[-1][1]["reason"] == "smtp_not_configured"


async def test_without_notify_there_is_no_result_event(stand: Stand) -> None:
    await stand.request(notify=False)
    (row,) = await stand.rows()
    assert await stand.mail.deliver(row.id) is True
    assert await stand.outbox() == []


async def test_eds_request_uses_its_own_pair_and_lost_enqueue_is_swept(stand: Stand) -> None:
    await stand.request(key="eds:letter:77", publisher="eds", secret=PAIR_EDS)
    (row,) = await stand.rows()
    assert (row.source, row.status) == ("eds", "queued")
    stand.queued.clear()
    assert await stand.mail.sweep() == 0, "свежую строку сборщик не трогает"
    later = datetime.now(UTC) + timedelta(minutes=10)
    assert await stand.mail.sweep(now=later) == 1
    assert stand.queued == [row.id]
