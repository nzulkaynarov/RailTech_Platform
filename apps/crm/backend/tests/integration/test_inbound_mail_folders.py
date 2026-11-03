"""Папки «Спам» и загрузка писем за период (W18A-P2-2) на Postgres.

IMAP — фейковый сервер с двумя папками (INBOX и «Spam» с флагом `\\Junk`), клиент — настоящий без
TLS. Адреса и тексты вымышленные.
"""

import asyncio
import contextlib
import functools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, ValidationFailedError
from app.domain.inbound_folders import TASK_WINDOW_DAYS, pick_history
from app.main import create_app
from app.models.auth import AuditLog
from app.models.inbound_mail import InboundMailbox, InboundMailImport
from app.repositories import inbound_mail as repo_mail
from app.services import inbound_mail_history as history_module
from app.services.imap_connector import ImapConnectorService
from app.services.inbound_mail import InboundMailService
from app.services.inbound_mail_history import InboundMailHistory
from tests.fake_imap import FakeImapServer, Mailbox, PlainClient
from tests.integration.test_inbound_mail import BUCKET, SECRETS_KEY, Stand, _staff

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def _mail(n: int, sent: datetime | None = None, sender: str = "buyer@example.test") -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Отправитель {n} <{sender}>"
    msg["To"] = "info@company.test"
    msg["Subject"] = f"Письмо {n}"
    msg["Message-ID"] = f"<folders-{n}@example.test>"
    if sent is not None:
        msg["Date"] = format_datetime(sent)
    msg.set_content(f"Текст письма {n}.")
    return msg.as_bytes().replace(b"\n", b"\r\n")


class FolderStand(Stand):
    def __init__(self, sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> None:
        super().__init__(sessions, server)
        self.spam: Mailbox = server.folder("Spam", "\\HasNoChildren \\Junk")
        self.queued: list[int] = []
        self.who: Any = None

        async def enqueue(import_id: int) -> None:
            self.queued.append(import_id)

        self.history = InboundMailHistory(
            sessions, self.store, self.settings, PlainClient(), self.ingest, enqueue
        )

    async def configure(self) -> None:
        await super().configure()
        current = (await self.settings.get()).integrations.model_dump(mode="json")
        current["imap"]["folders"] = [
            {"name": "INBOX", "spam": False},
            {"name": "Spam", "spam": True},
        ]
        await self.settings.update("integrations", current, None)

    async def load_history(self, days: int) -> InboundMailImport:
        if self.who is None:
            self.who = await self.principal()
        started = await self.history.start(self.who, days)
        assert self.queued[-1] == started.id
        assert await self.history.run(started.id) == "done"
        async with self.sessions() as session:
            row = await session.get(InboundMailImport, started.id)
        assert row is not None
        return row


@pytest.fixture
def server() -> Iterator[FakeImapServer]:
    with FakeImapServer() as running:
        yield running


@pytest.fixture
def stand(sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> FolderStand:
    return FolderStand(sessions, server)


async def test_spam_folder_lands_in_suspect_tab_not_queue(stand: FolderStand) -> None:
    await stand.configure()
    stand.server.box.add(1, _mail(1))
    stand.spam.add(5, _mail(2, sender="promo@spam.test"))

    result = await stand.ingest.poll()

    assert (result.status, result.created) == ("ok", 2)
    by_subject = {m.subject: m for m in await stand.mails()}
    assert by_subject["Письмо 1"].status == "new"
    assert (by_subject["Письмо 2"].status, by_subject["Письмо 2"].mailbox) == ("spam", "Spam")
    page = await stand.service().page(await stand.clerk(), "new")
    assert [i.subject for i in page.items] == ["Письмо 1"], (
        "спам не в очереди и не в «Моих задачах»"
    )
    assert (page.counts.new, page.counts.spam) == (1, 1)
    assert [i.subject for i in (await stand.service().page(await stand.clerk(), "spam")).items] == [
        "Письмо 2"
    ]
    async with stand.sessions() as session:
        states = (await session.scalars(select(InboundMailbox))).all()
    assert {(s.mailbox, s.uidvalidity, s.last_uid) for s in states} == {
        ("INBOX", 1001, 1),
        ("Spam", 2001, 5),
    }, "UID и UIDVALIDITY — на каждую папку"
    assert stand.server.box.writes == []
    assert stand.spam.writes == []
    assert not stand.server.box.selected_readwrite


async def test_moved_from_spam_to_inbox_is_one_row_back_in_queue(stand: FolderStand) -> None:
    await stand.configure()
    stand.spam.add(5, _mail(3))
    await stand.ingest.poll()
    (mail,) = await stand.mails()
    assert mail.status == "spam"

    # Человек в почте нажал «Не спам»: письмо переехало во «Входящие» под другим UID.
    del stand.spam.messages[5]
    stand.server.box.add(9, _mail(3))
    result = await stand.ingest.poll()

    assert result.created == 0
    (again,) = await stand.mails()
    assert again.id == mail.id, "одна строка по Message-ID"
    assert (again.status, again.mailbox) == ("new", "INBOX")


async def test_mail_from_inbox_seen_in_spam_stays_in_queue(stand: FolderStand) -> None:
    await stand.configure()
    stand.server.box.add(1, _mail(4))
    await stand.ingest.poll()
    stand.spam.add(7, _mail(4))
    await stand.ingest.poll()
    (mail,) = await stand.mails()
    assert (mail.status, mail.mailbox) == ("new", "INBOX")


async def test_not_spam_and_discard(stand: FolderStand) -> None:
    await stand.configure()
    stand.spam.add(1, _mail(5))
    stand.spam.add(2, _mail(6))
    await stand.ingest.poll()
    first, second = await stand.mails()
    who = await stand.principal()
    service = stand.service()

    await service.not_spam(who, first.id)
    await service.discard(who, second.id)

    first, second = await stand.mails()
    assert first.status == "new", "«Не спам» — обычное «Ждёт разбора»"
    assert (second.status, second.outcome, second.archive_reason, second.handled_by) == (
        "done",
        "archived",
        "Спам",
        who.user_id,
    )
    with pytest.raises(ConflictError):
        await service.not_spam(who, first.id)  # уже в очереди
    with pytest.raises(ConflictError):
        await service.discard(who, second.id)
    async with stand.sessions() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action).where(AuditLog.action.like("inbound_mail.%"))
            )
        ).all()
    assert sorted(actions) == ["inbound_mail.discard", "inbound_mail.not_spam"]
    assert stand.spam.writes == [], "ящик на сервере не меняется"


async def test_history_loads_old_mail_once_and_keeps_tasks_clean(stand: FolderStand) -> None:
    await stand.configure()
    recent, old, older = NOW - timedelta(days=1), NOW - timedelta(days=10), NOW - timedelta(days=40)
    stand.server.box.add(1, _mail(10, older), older)
    stand.server.box.add(2, _mail(11, old), old)
    stand.server.box.add(3, _mail(12, recent), recent)
    stand.spam.add(4, _mail(13, old), old)
    await stand.ingest.poll()  # первый опрос — только последние дни
    assert [m.subject for m in await stand.mails()] == ["Письмо 12"]

    row = await stand.load_history(30)

    assert (row.status, row.found, row.processed, row.created, row.limited) == (
        "done",
        3,
        3,
        2,
        False,
    ), "за 30 дней: 3 письма, новых 2 (свежее уже было), 40-дневное не тронуто"
    by_subject = {m.subject: m for m in await stand.mails()}
    assert set(by_subject) == {"Письмо 11", "Письмо 12", "Письмо 13"}
    assert (by_subject["Письмо 11"].status, by_subject["Письмо 11"].from_history) == ("new", True)
    assert by_subject["Письмо 12"].from_history is False
    assert (by_subject["Письмо 13"].status, by_subject["Письмо 13"].from_history) == ("spam", True)

    service = stand.service()
    tasks = await service.page(await stand.clerk(), "new", history=False)
    assert [i.subject for i in tasks.items] == ["Письмо 12"], (
        f"«Мои задачи» — только письма за {TASK_WINDOW_DAYS} дня"
    )
    assert [
        i.subject for i in (await service.page(await stand.clerk(), "new", history=True)).items
    ] == ["Письмо 11"]
    everything = await service.page(await stand.clerk(), "new")
    assert [i.subject for i in everything.items] == ["Письмо 12", "Письмо 11"], "по дате письма"
    assert (everything.counts.new, everything.counts.history) == (2, 1)

    again = await stand.load_history(90)
    assert (again.found, again.created) == (4, 1), "повтор безопасен: новое только 40-дневное"
    assert len(await stand.mails()) == 4
    assert stand.server.box.writes == []
    assert stand.spam.writes == []


async def test_history_limit_takes_newest_and_says_so(
    stand: FolderStand, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stand.configure()
    for n in range(1, 4):
        day = NOW - timedelta(days=10 + n)
        stand.server.box.add(n, _mail(20 + n, day), day)
    monkeypatch.setattr(history_module, "pick_history", functools.partial(pick_history, limit=2))

    row = await stand.load_history(30)

    assert (row.found, row.created, row.limited) == (2, 2, True)
    assert {m.uid for m in await stand.mails()} == {2, 3}, "новые (больший UID) раньше"


async def test_history_start_is_single_and_validated(stand: FolderStand) -> None:
    who = await stand.principal()
    with pytest.raises(ConflictError):
        await stand.history.start(who, 30)  # приём не настроен
    await stand.configure()
    with pytest.raises(ValidationFailedError):
        await stand.history.start(who, 5)
    first = await stand.history.start(who, 30)
    second = await stand.history.start(who, 90)
    assert second.id == first.id, "уже идёт — та же загрузка, вторая задача не ставится"
    assert stand.queued == [first.id]
    # Зависшая (воркер упал) новой не мешает.
    await _stale(stand.sessions, first.id)
    third = await stand.history.start(who, 7)
    assert third.id != first.id


async def test_two_starts_at_once_give_one_import(stand: FolderStand) -> None:
    """Два «Загрузить» одновременно (двойной клик, две вкладки) — одна загрузка: advisory-блокировка
    (мутационная проверка — в PR: без неё обе проходят проверку «уже идёт» и строк две)."""
    await stand.configure()
    who = await stand.principal()
    gate = asyncio.Barrier(2)
    original = repo_mail.running_import

    async def running_then_wait(session: AsyncSession, fresh_after: datetime) -> Any:
        found = await original(session, fresh_after)
        with contextlib.suppress(TimeoutError):  # под блокировкой второй сюда не дойдёт
            await asyncio.wait_for(gate.wait(), 0.5)
        return found

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(repo_mail, "running_import", running_then_wait)
        first, second = await asyncio.gather(
            stand.history.start(who, 30), stand.history.start(who, 30)
        )
    assert first.id == second.id
    async with stand.sessions() as session:
        rows = (await session.scalars(select(InboundMailImport))).all()
    assert len(rows) == 1
    assert len(stand.queued) == 1


async def _stale(sessions: async_sessionmaker[AsyncSession], import_id: int) -> None:
    """`updated_at` ставит триггер — состарить строку напрямую, мимо триггера."""
    from sqlalchemy import text

    async with sessions() as session, session.begin():
        await session.execute(text("ALTER TABLE inbound_mail_import DISABLE TRIGGER USER"))
        await session.execute(
            text(
                "UPDATE inbound_mail_import SET updated_at = now() - interval '2 hours' "
                "WHERE id = :i"
            ),
            {"i": import_id},
        )
        await session.execute(text("ALTER TABLE inbound_mail_import ENABLE TRIGGER USER"))


async def test_find_folders_and_status(stand: FolderStand) -> None:
    connector = ImapConnectorService(stand.sessions, stand.settings, stand.store, PlainClient())
    assert (await connector.folders()).error_kind == "not_configured"
    await stand.configure()
    stand.server.folder("&BCEEPwQwBDw-")

    found = await connector.folders()

    assert found.ok
    assert [(f.name, f.label, f.junk) for f in found.folders] == [
        ("INBOX", "INBOX", False),
        ("Spam", "Spam", True),
        ("&BCEEPwQwBDw-", "Спам", False),
    ]
    assert found.spam_suggestion == "Spam", "по флагу \\Junk"
    await stand.ingest.poll()
    status = await connector.status()
    assert [(f.name, f.spam) for f in status.folders] == [("INBOX", False), ("Spam", True)]
    assert status.last_ok_at is not None
    assert status.history is None


# --- API и права -------------------------------------------------------------------------------


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, server: FakeImapServer
) -> Iterator[tuple[TestClient, FolderStand]]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        stand = FolderStand(sessions, server)
        stand.settings = container.settings_service
        container.__dict__["inbound_mail"] = InboundMailService(
            sessions,
            container.settings_service,
            container.mail_service,
            stand.storage,
            BUCKET,
            container.imap_connector.configured,
            container.imap_connector.address,
        )
        yield test_client, stand


async def test_api_spam_tab_and_actions_by_rights(
    client: tuple[TestClient, FolderStand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = client
    clerk = await _staff(http, sessions, "clerk-s@railtech.uz", "tpl:REGISTRAR")
    seller = await _staff(http, sessions, "seller-s@railtech.uz", "tpl:MANAGER_ALL")
    await stand.configure()
    stand.spam.add(1, _mail(30))
    stand.spam.add(2, _mail(31))
    await stand.ingest.poll()
    ids = [m.id for m in await stand.mails()]

    page = http.get("/api/v1/inbound-mail", params={"view": "spam"}, headers=clerk).json()
    assert sorted(i["id"] for i in page["items"]) == sorted(ids)
    assert (page["counts"]["new"], page["counts"]["history"], page["counts"]["spam"]) == (0, 0, 2)
    assert page["items"][0]["from_history"] is False
    tasks = http.get("/api/v1/inbound-mail", params={"view": "tasks"}, headers=clerk)
    assert (tasks.status_code, tasks.json()["items"]) == (200, [])

    assert http.post(f"/api/v1/inbound-mail/{ids[0]}/not-spam", headers=seller).status_code == 403
    assert http.post(f"/api/v1/inbound-mail/{ids[0]}/not-spam", headers=clerk).status_code == 204
    assert http.post(f"/api/v1/inbound-mail/{ids[1]}/discard", headers=clerk).status_code == 204
    assert http.post(f"/api/v1/inbound-mail/{ids[1]}/discard", headers=clerk).status_code == 409
    queue = http.get("/api/v1/inbound-mail", headers=clerk).json()
    assert [i["id"] for i in queue["items"]] == [ids[0]]
    # Настройка приёма — только админ.
    assert http.post("/api/v1/integrations/imap/folders", headers=clerk).status_code == 403
    body: dict[str, Any] = {"days": 30}
    assert (
        http.post("/api/v1/integrations/imap/history", json=body, headers=clerk).status_code == 403
    )
