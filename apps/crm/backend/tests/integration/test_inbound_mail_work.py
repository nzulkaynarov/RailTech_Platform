"""Общий ящик как обращение (W18A-P2-3) на Postgres: «в работе», цепочки, адресаты, представления.

IMAP — фейковый сервер, клиент — настоящий без TLS; почтовый сервис ответа — подставной. Адреса и
тексты вымышленные. Тест гонки — с защитой `FOR UPDATE` (мутационная проверка — в описании PR).
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, ForbiddenError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.email import EmailLog
from app.models.inbound_mail import InboundMail
from app.security import audit
from app.security.principal import Principal
from app.services.inbound_mail import InboundMailService, MailAccess
from tests.fake_imap import FakeImapServer
from tests.integration.test_inbound_mail import BUCKET, SECRETS_KEY, Stand, _staff

pytestmark = pytest.mark.integration

BOX = "inbox@company.test"  # логин приёма = адрес общего ящика
IVANOV, PETROV = "ivanov@railtech.uz", "petrov@railtech.uz"


def _raw(
    n: int,
    *,
    to: str = BOX,
    cc: str | None = None,
    sender: str = "buyer@example.test",
    reply_to: str | None = None,
    references: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Покупатель {n} <{sender}>"
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = f"Запрос {n}"
    msg["Message-ID"] = f"<work-{n}@example.test>"
    if reply_to:
        msg["In-Reply-To"] = f"<{reply_to}>"
    if references:
        msg["References"] = references
    msg.set_content(f"Нужны шпалы, партия {n}.")
    return msg.as_bytes().replace(b"\n", b"\r\n")


class SentMail:
    """Почтовый сервис ответа: запоминает письма, настоящую отправку не делает."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_rendered(self, template: str, to: str, rendered: Any, **kw: Any) -> Any:
        self.sent.append({"to": to, "subject": rendered.subject, **kw})
        return type(
            "V", (), {"id": len(self.sent), "status": "queued", "created_at": datetime.now(UTC)}
        )()


@pytest.fixture
def server() -> Iterator[FakeImapServer]:
    with FakeImapServer() as running:
        yield running


@pytest.fixture
def stand(sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> Stand:
    return Stand(sessions, server)


async def _ingest(stand: Stand, *messages: tuple[int, bytes]) -> list[InboundMail]:
    await stand.configure()
    for uid, raw in messages:
        stand.server.box.add(uid, raw)
    await stand.ingest.poll()
    return await stand.mails()


async def _row(stand: Stand, mail_id: int) -> InboundMail:
    async with stand.sessions() as session:
        row = await session.get(InboundMail, mail_id)
    assert row is not None
    return row


async def _roots(stand: Stand) -> list[InboundMail]:
    return [m for m in await stand.mails() if m.thread_root_id is None]


def _service(stand: Stand, mail: Any = None) -> Any:
    service = stand.service(mail)
    service._mailbox_address = _box
    return service


async def _box() -> str | None:
    return BOX


async def _people(stand: Stand) -> tuple[Principal, Principal]:
    return await stand.principal(IVANOV), await stand.principal(PETROV)


# --- адресаты и «адресовано лично» -----------------------------------------------------------


async def test_personal_mail_goes_to_the_addressee_in_work(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1, to=f"{IVANOV}, client@example.test", cc=BOX)))

    assert (mail.status, mail.personal, mail.assignee_id) == ("in_work", True, ivanov.user_id)
    assert mail.assigned_at is not None
    assert mail.to_addrs == [IVANOV, "client@example.test"]
    assert mail.cc_addrs == [BOX], "«Кому» и копия хранятся раздельно"
    assert mail.to_staff_ids == [ivanov.user_id]

    # Делопроизводитель видит его в «Все в работе», не в «Новых» и не в «Моих».
    clerk = await stand.clerk()
    service = stand.service()
    assert (await service.page(clerk, "new")).items == []
    in_work = await service.page(clerk, "in_work")
    assert [i.id for i in in_work.items] == [mail.id]
    assert in_work.items[0].personal is True
    assert in_work.items[0].assignee is not None
    assert in_work.items[0].assignee.id == ivanov.user_id
    assert (await service.page(clerk, "mine")).items == []

    # Сотрудник без раздела первой линии видит своё письмо и больше ничего.
    mine = await service.page(MailAccess(ivanov, False), "mine")
    assert [i.id for i in mine.items] == [mail.id]
    stranger = MailAccess(petrov, False)
    assert (await service.page(stranger, "all")).items == []
    with pytest.raises(ForbiddenError):
        await service.get(stranger, mail.id)


@pytest.mark.parametrize(
    ("rule", "to", "cc", "status", "assignee"),
    [
        (True, IVANOV, BOX, "in_work", IVANOV),
        (False, IVANOV, BOX, "new", None),  # правило выключено: всё в «Новые», как раньше
        (True, BOX, IVANOV, "new", None),  # ящик адресат, сотрудник — для сведения
        (True, f"{PETROV}, {IVANOV}", BOX, "in_work", PETROV),  # первый в «Кому» — исполнитель
    ],
)
async def test_personal_rule_table(
    stand: Stand, rule: bool, to: str, cc: str, status: str, assignee: str | None
) -> None:
    people = {IVANOV: (await _people(stand))[0], PETROV: (await _people(stand))[1]}
    await stand.configure()
    current = (await stand.settings.get()).integrations.model_dump(mode="json")
    current["imap"]["personal_rule"] = rule
    await stand.settings.update("integrations", current, None)
    stand.server.box.add(1, _raw(1, to=to, cc=cc))
    await stand.ingest.poll()

    (mail,) = await stand.mails()
    assert mail.status == status
    expected = people[assignee].user_id if assignee else None
    assert mail.assignee_id == expected


async def test_coaddressees_and_copy_staff_see_the_personal_mail(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    sidorov = await stand.principal("sidorov@railtech.uz")
    (mail,) = await _ingest(
        stand, (1, _raw(1, to=f"{IVANOV}, {PETROV}", cc=f"{BOX}, sidorov@railtech.uz"))
    )
    assert mail.assignee_id == ivanov.user_id
    assert (mail.to_staff_ids, mail.cc_staff_ids) == (
        [ivanov.user_id, petrov.user_id],
        [sidorov.user_id],
    )
    service = _service(stand)
    card = await service.get(MailAccess(petrov, False), mail.id)  # соадресат
    assert [a.staff.name if a.staff else None for a in card.to] == ["ivanov", "petrov"]
    assert [(a.email, a.mailbox) for a in card.cc] == [(BOX, True), ("sidorov@railtech.uz", False)]
    assert card.cc[1].staff is not None
    await service.get(MailAccess(sidorov, False), mail.id)  # «для сведения»
    # Соадресат не ведёт письмо: отвечать и забирать ему нельзя.
    with pytest.raises(ForbiddenError):
        await service.reply(MailAccess(petrov, False), mail.id, "Привет")


async def test_inactive_or_unknown_address_is_not_staff(stand: Stand) -> None:
    (mail,) = await _ingest(stand, (1, _raw(1, to="stranger@railtech.uz", cc=BOX)))
    assert (mail.status, mail.personal, mail.to_staff_ids) == ("new", False, [])


async def test_same_message_in_two_folders_is_one_record(stand: Stand) -> None:
    """Одно письмо в двух опрашиваемых папках — одна запись по Message-ID (To/Cc первой папки)."""
    await _people(stand)
    await stand.configure()
    current = (await stand.settings.get()).integrations.model_dump(mode="json")
    current["imap"]["folders"] = [
        {"name": "INBOX", "spam": False},
        {"name": "Archive", "spam": False},
    ]
    await stand.settings.update("integrations", current, None)
    other = stand.server.folder("Archive")
    stand.server.box.add(1, _raw(1, to=BOX, cc=IVANOV))
    other.add(9, _raw(1, to=f"{IVANOV}, extra@example.test", cc=BOX))
    await stand.ingest.poll()
    (mail,) = await stand.mails()
    assert (mail.to_addrs, mail.cc_addrs) == ([BOX], [IVANOV])


# --- «в работе»: взять, перехватить, вернуть ---------------------------------------------------


async def test_first_action_takes_the_mail_and_others_get_409(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)

    await service.take(ivanov, mail.id)
    await service.take(ivanov, mail.id)  # повтор своего — без изменений
    row = await _row(stand, mail.id)
    assert (row.status, row.assignee_id) == ("in_work", ivanov.user_id)

    for action in (
        service.take(petrov, mail.id),
        service.archive(petrov, mail.id, "нужно разобрать"),
        service.create_lead(petrov, mail.id),
        service.registration(petrov, mail.id, "start"),
    ):
        with pytest.raises(ConflictError) as raised:
            await action
        assert raised.value.details["reason"] == "mail_in_work_by_other"
        assert raised.value.details["assignee_name"] == "ivanov"
        assert raised.value.details["assigned_at"]

    # «Забрать себе» — осознанно, с записью в журнал.
    await service.take(petrov, mail.id, takeover=True)
    assert (await _row(stand, mail.id)).assignee_id == petrov.user_id
    card = await service.get(await stand.clerk(), mail.id)
    assert [e.action for e in card.journal] == ["take", "takeover"]
    assert card.journal[0].actor is not None
    assert card.journal[0].actor.id == ivanov.user_id


async def test_first_action_takes_automatically(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    await _service(stand).registration(ivanov, mail.id, "start")  # открыл регистрацию ВХ
    row = await _row(stand, mail.id)
    assert (row.status, row.assignee_id) == ("registering", ivanov.user_id)
    assert row.registering_at is not None


async def test_two_people_cannot_act_on_one_mail_at_once(
    stand: Stand, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Двое одновременно берут одно письмо: строка под `FOR UPDATE` — успех у одного, у второго 409
    «уже в работе у …». Запись журнала задержана, чтобы без блокировки оба успели прочитать «Новое»
    (мутационная проверка: убрать `with_for_update` в `repo.get` — тест краснеет)."""
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    original = audit.record

    async def slow_record(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0.3)
        await original(*args, **kwargs)

    monkeypatch.setattr(audit, "record", slow_record)

    results = await asyncio.gather(
        service.take(ivanov, mail.id),
        service.take(petrov, mail.id),
        return_exceptions=True,
    )

    failed = [r for r in results if isinstance(r, ConflictError)]
    assert len(failed) == 1, results
    assert failed[0].details["reason"] == "mail_in_work_by_other"
    assert results.count(None) == 1
    winner = ivanov if results[0] is None else petrov
    assert (await _row(stand, mail.id)).assignee_id == winner.user_id


async def test_release_returns_to_new_and_journal_remembers(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    await service.take(ivanov, mail.id)

    with pytest.raises(ConflictError):  # чужое «в работе» вернуть нельзя
        await service.release(MailAccess(petrov, True), mail.id)
    await service.release(MailAccess(ivanov, True), mail.id)

    row = await _row(stand, mail.id)
    assert (row.status, row.assignee_id, row.assigned_at) == ("new", None, None)
    card = await service.get(await stand.clerk(), mail.id)
    assert [e.action for e in card.journal] == ["take", "release"]


async def test_archived_mail_returns_to_new_from_done_tab(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    await service.archive(ivanov, mail.id, "рассылка")

    done = await service.page(MailAccess(petrov, True), "done")
    (item,) = done.items
    assert item.status == "done"
    assert item.result is not None
    assert (item.result.outcome, item.result.reason) == ("archived", "рассылка")
    assert item.result.by is not None
    assert item.result.by.id == ivanov.user_id

    await service.release(MailAccess(petrov, True), mail.id)  # первая линия возвращает архив
    row = await _row(stand, mail.id)
    assert (row.status, row.outcome, row.archive_reason, row.handled_by) == (
        "new",
        None,
        None,
        None,
    )
    # Сотрудник без раздела первой линии разобранное не возвращает.
    await service.archive(petrov, mail.id, "ещё раз")
    with pytest.raises(ConflictError):
        await service.release(MailAccess(petrov, False), mail.id)


# --- ответ ------------------------------------------------------------------------------------


async def test_reply_marks_done_with_outcome_and_awaiting_keeps_it_in_work(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    first, second = await _ingest(stand, (1, _raw(1)), (2, _raw(2)))
    sender = SentMail()
    service = _service(stand, sender)

    await service.reply(MailAccess(ivanov, True), first.id, "КП пришлём завтра.")
    await service.reply(MailAccess(ivanov, True), second.id, "Уточните сроки.", awaiting=True)

    done, waiting = await _row(stand, first.id), await _row(stand, second.id)
    assert (done.status, done.outcome, done.handled_by) == ("done", "replied", ivanov.user_id)
    assert (waiting.status, waiting.assignee_id) == ("in_work", ivanov.user_id)
    assert [m["to"] for m in sender.sent] == ["buyer@example.test"] * 2


async def test_reply_all_keeps_the_copy_except_the_mailbox_and_sender(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(
        stand,
        (1, _raw(1, to=f"{BOX}, boss@example.test", cc=f"{PETROV}, buyer@example.test")),
    )
    sender = SentMail()
    service = _service(stand, sender)
    card = await service.get(await stand.clerk(), mail.id)
    assert card.reply_all_copy == ["boss@example.test", PETROV]

    me = MailAccess(ivanov, True)
    await service.reply(me, mail.id, "Всем: отправим.", reply_all=True, awaiting=True)
    await service.reply(me, mail.id, "Только вам.", reply_all=False, awaiting=True)
    all_reply, plain = sender.sent
    assert all_reply["thread_headers"]["Cc"] == f"boss@example.test, {PETROV}"
    assert "Cc" not in plain["thread_headers"], "«Ответить» — только отправителю"


async def test_personal_assignee_without_first_line_right_can_reply_and_return(
    stand: Stand,
) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1, to=IVANOV, cc=BOX)))
    sender = SentMail()
    service = _service(stand, sender)
    mine = MailAccess(ivanov, False)

    await service.release(mine, mail.id)  # «передать делопроизводителю»
    assert (await _row(stand, mail.id)).status == "new"
    with pytest.raises(ForbiddenError):  # теперь письмо не его
        await service.reply(mine, mail.id, "Отвечу сам")
    await service.take(ivanov, mail.id)  # (в API это действие первой линии; здесь — состояние)
    await service.reply(mine, mail.id, "Отвечаю.")
    assert (await _row(stand, mail.id)).outcome == "replied"


# --- цепочки ----------------------------------------------------------------------------------


async def test_client_reply_joins_the_thread_and_reopens_with_the_same_assignee(
    stand: Stand,
) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand, SentMail())
    await service.reply(MailAccess(ivanov, True), mail.id, "Пришлём КП.")
    assert (await _row(stand, mail.id)).status == "done"
    async with stand.sessions() as session, session.begin():  # след настоящей отправки
        session.add(
            EmailLog(
                to_email="buyer@example.test",
                subject="Re: Запрос 1",
                template="inbound_reply",
                lang="ru",
                status="sent",
                ref_kind="inbound_mail",
                ref_id=str(mail.id),
            )
        )

    stand.server.box.add(
        2, _raw(2, reply_to="work-1@example.test", references="<work-1@example.test>")
    )
    stand.server.box.add(3, _raw(3, references="<work-1@example.test> <work-2@example.test>"))
    await stand.ingest.poll()

    roots = await _roots(stand)
    assert [m.id for m in roots] == [mail.id], "ответы не создают новых строк списка"
    root = await _row(stand, mail.id)
    assert (root.status, root.thread_reply, root.assignee_id) == ("new", True, ivanov.user_id)
    assert (root.outcome, root.handled_by) == (None, None)
    clerk = await stand.clerk()
    page = await service.page(clerk, "new")
    assert [(i.id, i.thread_reply, i.messages_count) for i in page.items] == [(mail.id, True, 3)]
    assert page.items[0].assignee is not None
    assert page.items[0].assignee.id == ivanov.user_id, "прежний исполнитель — справкой"

    card = await service.get(clerk, mail.id)
    assert card.messages[0].id == mail.id
    assert len(card.messages) == 3
    assert len(card.replies) == 1, "наш ответ — из журнала почты, рядом с входящими"
    assert card.replies[0].to_email == "buyer@example.test"
    assert "thread_reply" in [e.action for e in card.journal]


async def test_reply_goes_to_the_latest_incoming_message_of_the_thread(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    stand.server.box.add(
        2, _raw(2, reply_to="work-1@example.test", sender="colleague@example.test")
    )
    await stand.ingest.poll()
    sender = SentMail()
    await _service(stand, sender).reply(MailAccess(ivanov, True), mail.id, "Ответ")
    (sent,) = sender.sent
    assert sent["to"] == "colleague@example.test"
    assert sent["thread_headers"]["In-Reply-To"] == "<work-2@example.test>"
    assert sent["thread_headers"]["References"] == "<work-2@example.test>"
    assert sent["ref"] == ("inbound_mail", str(mail.id))


async def test_reply_in_open_record_only_marks_it_fresh(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    await service.take(ivanov, mail.id)
    await service.mark_read(MailAccess(petrov, True), mail.id)
    stand.server.box.add(2, _raw(2, reply_to="work-1@example.test"))
    await stand.ingest.poll()

    row = await _row(stand, mail.id)
    assert (row.status, row.assignee_id, row.thread_reply) == ("in_work", ivanov.user_id, False)
    page = await service.page(MailAccess(petrov, True), "in_work")
    assert page.items[0].unread is True, "новое письмо в цепочке — снова не прочитано"


async def test_spam_folder_does_not_continue_threads(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    await _service(stand).archive(ivanov, mail.id, "рассылка")
    await stand.ingest.poll()
    current = (await stand.settings.get()).integrations.model_dump(mode="json")
    current["imap"]["folders"] = [{"name": "INBOX", "spam": False}, {"name": "Junk", "spam": True}]
    await stand.settings.update("integrations", current, None)
    stand.server.folder("Junk", "\\HasNoChildren \\Junk").add(
        4, _raw(4, reply_to="work-1@example.test")
    )
    await stand.ingest.poll()

    rows = {m.subject: m for m in await stand.mails()}
    assert rows["Запрос 4"].thread_root_id is None
    assert rows["Запрос 4"].status == "spam"
    assert (await _row(stand, mail.id)).status == "done", "подделка In-Reply-To не оживляет запись"


# --- представления, поиск, прочитано, массовый архив --------------------------------------------


async def test_views_counts_search_and_tasks(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    rows = await _ingest(stand, *[(n, _raw(n, sender=f"s{n}@example.test")) for n in range(1, 5)])
    service = _service(stand)
    clerk = await stand.clerk()
    first, second, third, _ = [m.id for m in rows]
    await service.take(ivanov, first)
    await service.take(petrov, second)
    await service.archive(ivanov, third, "рассылка")

    ivanov_access = MailAccess(ivanov, True)
    page = await service.page(ivanov_access, "new")
    assert len(page.items) == 1
    counts = page.counts
    assert (counts.new, counts.mine, counts.in_work, counts.done, counts.spam, counts.all) == (
        1,
        1,
        2,
        1,
        0,
        4,
    )
    assert [i.id for i in (await service.page(ivanov_access, "mine")).items] == [first]
    assert {i.id for i in (await service.page(clerk, "in_work")).items} == {first, second}
    # «Мои задачи»: новые не из истории и мои в работе — чужие «в работе» и разобранные не приходят.
    tasks = await service.page(ivanov_access, "tasks")
    assert {i.id for i in tasks.items} == {first, rows[3].id}
    assert [i.id for i in (await service.page(clerk, "all", q="s2@example")).items] == [second]
    assert [i.id for i in (await service.page(clerk, "all", q="Запрос 3")).items] == [third]
    assert (await service.page(clerk, "all", q="100%")).items == [], "% — обычный символ поиска"


async def test_read_marks_are_per_person(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    a, b = MailAccess(ivanov, True), MailAccess(petrov, True)

    assert (await service.page(a, "new")).items[0].unread is True
    assert (await service.page(a, "new")).counts.unread_new == 1
    await service.mark_read(a, mail.id)
    assert (await service.page(a, "new")).items[0].unread is False
    assert (await service.page(a, "new")).counts.unread_new == 0
    assert (await service.page(b, "new")).items[0].unread is True, "прочитано — на человека"


async def test_bulk_archive_skips_foreign_and_handled_and_says_which(stand: Stand) -> None:
    ivanov, petrov = await _people(stand)
    rows = await _ingest(stand, *[(n, _raw(n)) for n in range(1, 6)])
    service = _service(stand)
    free1, free2, foreign, done, registering = [m.id for m in rows]
    await service.take(petrov, foreign)
    await service.archive(petrov, done, "уже")
    await service.registration(ivanov, registering, "start")
    await service.take(ivanov, free2)  # своё «в работе» архивируется тоже

    result = await service.bulk_archive(
        ivanov, [free1, free2, foreign, done, registering, 9999], "рассылки"
    )

    assert sorted(result.archived) == [free1, free2]
    skipped = {s.id: s for s in result.skipped}
    assert {k: v.reason for k, v in skipped.items()} == {
        foreign: "in_work_by_other",
        done: "handled",
        registering: "registering",
        9999: "missing",
    }
    assert skipped[foreign].assignee is not None
    assert skipped[foreign].assignee.name == "petrov"
    archived = await _row(stand, free1)
    assert (archived.status, archived.outcome, archived.archive_reason) == (
        "done",
        "archived",
        "рассылки",
    )
    assert (await _row(stand, foreign)).status == "in_work"


# --- регистрация ВХ --------------------------------------------------------------------------


async def test_registration_start_cancel_and_event_confirms(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)

    await service.registration(ivanov, mail.id, "start")
    await service.registration(ivanov, mail.id, "cancel")  # EDS отказал
    assert (await _row(stand, mail.id)).status == "in_work"
    await service.registration(ivanov, mail.id, "start")

    from tests.integration.test_inbound_mail import _registered

    async with stand.sessions() as session, session.begin():
        await service.accept_registered(session, _registered(mail.id))
    row = await _row(stand, mail.id)
    assert (row.status, row.outcome, row.eds_letter_number) == ("done", "registered", "ВХ-12/26")
    assert row.registering_at is None


async def test_registration_waits_for_eds_then_says_so(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1)))
    service = _service(stand)
    await service.registration(ivanov, mail.id, "start")
    clerk = await stand.clerk()

    fresh = (await service.page(clerk, "in_work")).items[0]
    assert (fresh.status, fresh.eds_waiting) == ("registering", False)
    async with stand.sessions() as session, session.begin():
        row = await session.get(InboundMail, mail.id)
        assert row is not None
        row.registering_at = datetime(2026, 1, 1, tzinfo=UTC)  # событие давно не приходит
    stale = (await service.page(clerk, "in_work")).items[0]
    assert stale.eds_waiting is True


# --- журнал -----------------------------------------------------------------------------------


async def test_journal_has_actions_without_mail_texts(stand: Stand) -> None:
    ivanov, _ = await _people(stand)
    (mail,) = await _ingest(stand, (1, _raw(1, to=IVANOV, cc=BOX)))
    service = _service(stand, SentMail())
    await service.reply(MailAccess(ivanov, True), mail.id, "Секретный текст ответа")

    card = await service.get(await stand.clerk(), mail.id)

    assert [e.action for e in card.journal] == ["personal", "reply"]
    assert "Секретный" not in str(card.journal)
    async with stand.sessions() as session:
        logged = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "inbound_mail.reply"))
        ).one()
    assert "Секретный" not in str(logged.after)


# --- HTTP и права --------------------------------------------------------------------------------


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, server: FakeImapServer
) -> Iterator[tuple[TestClient, Stand]]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        stand = Stand(sessions, server, container.settings_service)
        container.__dict__["inbound_mail"] = InboundMailService(
            sessions,
            container.settings_service,
            container.mail_service,
            stand.storage,
            BUCKET,
            container.imap_connector.configured,
            _box,
        )
        yield test_client, stand


async def test_api_in_work_conflict_and_personal_access_by_rights(
    client: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = client
    clerk = await _staff(http, sessions, "clerk-w@railtech.uz", "tpl:REGISTRAR")
    other = await _staff(http, sessions, "clerk-x@railtech.uz", "tpl:REGISTRAR")
    seller = await _staff(http, sessions, IVANOV, "tpl:MANAGER_ALL")
    await _ingest(stand, (1, _raw(1)), (2, _raw(2, to=IVANOV, cc=BOX)), (3, _raw(3)))
    first, personal, third = [m.id for m in await stand.mails()]
    base = "/api/v1/inbound-mail"

    assert http.post(f"{base}/{first}/take", json={}, headers=clerk).status_code == 204
    busy = http.post(f"{base}/{first}/archive", json={"reason": "рассылка"}, headers=other)
    assert busy.status_code == 409
    details = busy.json()["details"]
    assert (details["reason"], details["assignee_name"]) == ("mail_in_work_by_other", "clerk-w")
    taken = http.post(f"{base}/{first}/take", json={"takeover": True}, headers=other)
    assert taken.status_code == 204

    # Сотрудник без раздела первой линии: только своё письмо, действий первой линии нет.
    mine = http.get(base, params={"view": "mine"}, headers=seller).json()
    assert [i["id"] for i in mine["items"]] == [personal]
    assert mine["items"][0]["personal"] is True
    assert http.get(f"{base}/{personal}", headers=seller).status_code == 200
    assert http.post(f"{base}/{personal}/read", headers=seller).status_code == 204
    assert http.get(f"{base}/{first}", headers=seller).status_code == 403
    assert http.post(f"{base}/{personal}/lead", headers=seller).status_code == 403
    assert http.post(f"{base}/{personal}/take", json={}, headers=seller).status_code == 403
    assert (
        http.post(
            f"{base}/bulk-archive", json={"ids": [personal], "reason": "тест"}, headers=seller
        ).status_code
        == 403
    )
    unread = http.get(base, params={"view": "mine"}, headers=seller).json()["items"][0]["unread"]
    assert unread is False

    # Первая линия: пакетный архив, регистрация, возврат.
    bulk = http.post(
        f"{base}/bulk-archive", json={"ids": [first, third], "reason": "рассылки"}, headers=clerk
    )
    assert bulk.status_code == 200, bulk.text
    out = bulk.json()
    assert out["archived"] == [third]
    assert [(s["id"], s["reason"]) for s in out["skipped"]] == [(first, "in_work_by_other")]
    start = http.post(f"{base}/{first}/registration", json={"state": "start"}, headers=clerk)
    assert start.status_code == 409
    assert http.post(f"{base}/{third}/release", headers=clerk).status_code == 204
    counts = http.get(base, headers=clerk).json()["counts"]
    assert (counts["new"], counts["in_work"]) == (1, 2)
