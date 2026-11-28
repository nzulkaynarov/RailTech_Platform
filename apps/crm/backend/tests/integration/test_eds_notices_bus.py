"""Уведомления сотрудникам по поручениям входящих EDS (P8b) на реальном Postgres.

EDS публикует `uz.railtech.eds.notice.requested.v1`; CRM принимает его настоящим приёмником шины
(подпись пары `eds → crm`), обработка — `process_inbox`, сообщения Telegram — после коммита, как у
событий ERP. Проверяется: строка колокольчика каждому активному получателю, Telegram тем, у кого он
привязан; повтор доставки — один эффект; откат обработки — ничего; лишнее поле `data` принимается.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import runtime
from app.models.auth import User
from app.models.staff_tickets import StaffNotification
from app.services.eds_notices import (
    DOCUMENT_NOTICE_TYPE,
    DOCUMENT_NOTICE_TYPE_V2,
    NOTICE_TYPE,
    SIGNING_EXPIRING_TYPE,
    EdsNoticeService,
    tab_of,
)
from tests.bus_events import envelope_for, signed_request
from tests.integration.bus_harness import FakeContainer, Harness
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration

LETTER_ID = "40000000-0000-4000-8000-000000000112"
PAIR_EDS = "eds-notice-test-pair-eds-crm-0001"  # фиктивный секрет пары eds → crm


class EdsContainer(FakeContainer):
    def __init__(self, harness: Harness, notices: EdsNoticeService) -> None:
        super().__init__(harness.service, harness.bus)
        self.eds_notices = notices


class Stand:
    def __init__(self, harness: Harness) -> None:
        self.h = harness
        self.notices = EdsNoticeService(harness.notices, "https://platform.example.com")
        runtime.install(cast(Any, EdsContainer(harness, self.notices)))

    async def receive(
        self, data: dict[str, Any], *, event_id: str | None = None, event_type: str = NOTICE_TYPE
    ) -> str:
        envelope = envelope_for(event_type, data, source="rt://eds", event_id=event_id)
        headers, body = signed_request(envelope, PAIR_EDS, publisher="eds")
        result = await self.h.bus.receive(headers, body)
        assert result.status_code == 200, result.body
        return str(envelope["id"])

    async def bell(self) -> list[StaffNotification]:
        async with self.h.sessions() as session:
            stmt = select(StaffNotification).order_by(StaffNotification.id)
            return list((await session.scalars(stmt)).all())


@pytest.fixture
async def stand(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stand]:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR_EDS)
    harness = Harness(sessions)
    yield Stand(harness)
    harness.close()


def notice(recipients: list[int], **over: Any) -> dict[str, Any]:
    return {
        "notice_key": f"instruction:{uuid.uuid4()}:assigned",
        "kind": "instruction_assigned",
        "recipients": recipients,
        "title": "Поручение по письму ВХ-112/26",
        "subtitle": "Требование ГНК о пояснениях · срок 05.11.2026",
        "letter": {
            "eds_letter_id": LETTER_ID,
            "number": "ВХ-112/26",
            "subject": "Требование ГНК о пояснениях",
        },
        "due": "2026-11-05",
        "actor": {"type": "staff", "crm_user_id": 3},
        **over,
    }


async def _link(
    sessions: async_sessionmaker[AsyncSession],
    user_id: int,
    tg: int,
    **flags: bool,
) -> None:
    """Привязать Telegram; `flags` — переключатели профиля (`notify_decisions`, `notify_tasks`)."""
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == user_id).values(tg_user_id=tg, **flags))


async def test_bell_and_telegram_for_each_active_recipient(stand: Stand) -> None:
    sessions = stand.h.sessions
    executor, _ = await make_user(sessions, "exec@x.uz", ["manager"])
    reader, _ = await make_user(sessions, "reader@x.uz", ["manager"])
    gone, _ = await make_user(sessions, "gone@x.uz", ["manager"])
    await _link(sessions, executor.id, 8101, notify_tasks=True)
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == gone.id).values(is_active=False))

    event_id = await stand.receive(notice([executor.id, reader.id, gone.id, 999_999]))
    assert await stand.h.process(event_id) == "processed"

    rows = await stand.bell()
    assert [(r.user_id, r.kind, r.tab) for r in rows] == [
        (executor.id, "eds.instruction_assigned", "decisions"),
        (reader.id, "eds.instruction_assigned", "decisions"),
    ]
    first = rows[0]
    assert (first.object_kind, first.object_id, first.object_number) == (
        "letter",
        LETTER_ID,
        "ВХ-112/26",
    )
    assert first.subtitle == "Требование ГНК о пояснениях · срок 05.11.2026"
    # Telegram — только тому, у кого он привязан, после коммита обработки
    [(chat, text)] = stand.h.bot.sent
    assert chat == 8101
    assert text.startswith("Поручение по письму ВХ-112/26\nТребование ГНК")
    assert text.endswith(f"https://platform.example.com/eds/tasks/{LETTER_ID}")
    assert stand.h.bot.inbox_status_at_send == ["processed"]


async def test_repeated_delivery_gives_one_notification(stand: Stand) -> None:
    executor, _ = await make_user(stand.h.sessions, "rep@x.uz", ["manager"])
    event_id = str(uuid.uuid4())
    data = notice([executor.id])

    await stand.receive(data, event_id=event_id)
    await stand.receive(data, event_id=event_id)  # повтор доставки того же события
    assert await stand.h.process(event_id) == "processed"
    await stand.h.process(event_id)

    assert len(await stand.bell()) == 1


async def test_failed_processing_leaves_nothing(
    stand: Stand, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, _ = await make_user(stand.h.sessions, "rb@x.uz", ["manager"])
    await _link(stand.h.sessions, executor.id, 8102, notify_tasks=True)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("сбой после строки колокольчика")

    monkeypatch.setattr(stand.h.notices, "add", broken)
    event_id = await stand.receive(notice([executor.id]))
    assert await stand.h.process(event_id) != "processed"

    assert await stand.bell() == []
    assert stand.h.bot.sent == []
    assert await stand.h.notice(event_id) is None


async def test_unknown_field_is_accepted_and_kind_sets_the_tab(stand: Stand) -> None:
    executor, _ = await make_user(stand.h.sessions, "uf@x.uz", ["manager"])
    data = notice([executor.id], kind="letter_executed", subtitle=None, future_field={"x": 1})

    event_id = await stand.receive(data)
    assert await stand.h.process(event_id) == "processed"

    [row] = await stand.bell()
    assert (row.kind, row.tab, row.subtitle) == ("eds.letter_executed", "system", None)
    assert tab_of("extension_requested") == "decisions"
    assert tab_of("extension_decided") == "system"


async def test_reply_notice_points_to_the_outgoing_document(stand: Stand) -> None:
    """EDS-REPLY-1: уведомление про ответ на ВХ (`document`) ведёт в карточку исходящего."""
    registrar, _ = await make_user(stand.h.sessions, "regs@x.uz", ["manager"])
    await _link(stand.h.sessions, registrar.id, 8103, notify_tasks=True)
    doc_id = "50000000-0000-4000-8000-000000000201"
    data = notice(
        [registrar.id],
        title="Зарегистрируйте ответ на ВХ-112/26",
        subtitle="Пояснения · Алия Каримова",
        document={"eds_document_id": doc_id, "number": None, "subject": "Пояснения"},
    )

    event_id = await stand.receive(data)
    assert await stand.h.process(event_id) == "processed"

    [row] = await stand.bell()
    assert (row.object_kind, row.object_id, row.object_number) == ("document", doc_id, "ВХ-112/26")
    [(_, text)] = stand.h.bot.sent
    assert text.endswith(f"https://platform.example.com/eds/documents?doc={doc_id}&panel=open")

    registered = notice(
        [registrar.id],
        document={"eds_document_id": doc_id, "number": "ИСХ-014/26", "subject": "Пояснения"},
    )
    assert await stand.h.process(await stand.receive(registered)) == "processed"
    assert (await stand.bell())[-1].object_number == "ИСХ-014/26"


def expiring(recipients: list[int], **over: Any) -> dict[str, Any]:
    """Тело `signing_authority.expiring` (SIGN-2): как пример контракта, получатели — свои."""
    return {
        "notice_key": "signing-authority:6f1b2c3d:expiring:2026-11-19",
        "recipients": recipients,
        "title": "Доверенность Алии Каримовой заканчивается 19.11.2026",
        "subtitle": "Осталось 14 дней. Настройки → Права подписи: продлите или выдайте новую",
        "authority": {
            "eds_authority_id": "6f1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
            "holder": {"crm_user_id": 7, "full_name": "Алия Каримова"},
            "basis": "power_of_attorney",
            "basis_number": "17",
            "valid_to": "2026-11-19",
            "days_left": 14,
        },
        "actor": {"type": "system"},
        **over,
    }


async def test_signing_authority_reminder_reaches_the_register_keepers(stand: Stand) -> None:
    sessions = stand.h.sessions
    keeper, _ = await make_user(sessions, "keeper@x.uz", ["admin"])
    other, _ = await make_user(sessions, "other@x.uz", ["admin"])
    await _link(sessions, keeper.id, 8201)

    event_id = await stand.receive(
        expiring([keeper.id, other.id, 999_999], future_field=1), event_type=SIGNING_EXPIRING_TYPE
    )
    assert await stand.h.process(event_id) == "processed"

    rows = await stand.bell()
    assert [(r.user_id, r.kind, r.tab) for r in rows] == [
        (keeper.id, "eds.signing_authority_expiring", "decisions"),
        (other.id, "eds.signing_authority_expiring", "decisions"),
    ]
    assert (rows[0].object_kind, rows[0].object_id, rows[0].object_number) == (None, None, None)
    assert rows[0].title.startswith("Доверенность Алии Каримовой заканчивается")
    [(chat, text)] = stand.h.bot.sent
    assert chat == 8201
    assert text.endswith("https://platform.example.com/admin/signing")


async def test_signing_authority_reminder_repeated_delivery_gives_one_notification(
    stand: Stand,
) -> None:
    keeper, _ = await make_user(stand.h.sessions, "keeper2@x.uz", ["admin"])
    event_id = str(uuid.uuid4())
    data = expiring([keeper.id])
    await stand.receive(data, event_id=event_id, event_type=SIGNING_EXPIRING_TYPE)
    await stand.receive(data, event_id=event_id, event_type=SIGNING_EXPIRING_TYPE)
    assert await stand.h.process(event_id) == "processed"
    await stand.h.process(event_id)
    assert len(await stand.bell()) == 1


DOC_ID = "2f6b1c0e-8a3d-4e57-9c14-b0d7a5e3f812"


def document_notice(recipients: list[int], **over: Any) -> dict[str, Any]:
    """Тело `document.notice_requested` (СЦ-9): как пример контракта, получатели — свои."""
    return {
        "notice_key": f"document:{DOC_ID}:r1:memo_decided:approved",
        "kind": "memo_decided",
        "recipients": recipients,
        "title": "Служебка MEMO-2026/014 согласована",
        "subtitle": "Передана на оплату",
        "document": {
            "eds_document_id": DOC_ID,
            "number": "MEMO-2026/014",
            "subject": "Закупка расходных материалов",
        },
        "actor": {"type": "staff", "crm_user_id": 3},
        **over,
    }


async def test_document_notice_reaches_the_author_with_a_link_to_the_document(stand: Stand) -> None:
    author, _ = await make_user(stand.h.sessions, "author@x.uz", ["manager"])
    other, _ = await make_user(stand.h.sessions, "author2@x.uz", ["manager"])
    await _link(stand.h.sessions, author.id, 8301, notify_tasks=True)

    event_id = await stand.receive(
        document_notice([author.id, other.id, 999_999], future_field=1),
        event_type=DOCUMENT_NOTICE_TYPE,
    )
    assert await stand.h.process(event_id) == "processed"

    rows = await stand.bell()
    assert [(r.user_id, r.kind, r.tab) for r in rows] == [
        (author.id, "eds.memo_decided", "system"),
        (other.id, "eds.memo_decided", "system"),
    ]
    assert (rows[0].object_kind, rows[0].object_id, rows[0].object_number) == (
        "document",
        DOC_ID,
        "MEMO-2026/014",
    )
    [(chat, text)] = stand.h.bot.sent
    assert chat == 8301
    assert text.endswith(f"https://platform.example.com/eds/documents?doc={DOC_ID}&panel=open")


async def test_document_notice_for_a_draft_letter_uses_the_subject_as_label(stand: Stand) -> None:
    signer, _ = await make_user(stand.h.sessions, "signer@x.uz", ["admin"])
    data = document_notice(
        [signer.id],
        kind="letter_sign_requested",
        document={
            "eds_document_id": DOC_ID,
            "number": None,
            "subject": "Ответ на требование о пояснениях",
        },
    )
    assert (
        await stand.h.process(await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE))
        == "processed"
    )
    [row] = await stand.bell()
    assert (row.kind, row.tab, row.object_kind, row.object_number) == (
        "eds.letter_sign_requested",
        "decisions",
        "document",
        "Ответ на требование о пояснениях",
    )


async def test_missing_signer_notice_points_to_the_signing_settings(stand: Stand) -> None:
    keeper, _ = await make_user(stand.h.sessions, "keeper3@x.uz", ["admin"])
    await _link(stand.h.sessions, keeper.id, 8302)
    data = document_notice([keeper.id], kind="letter_signer_missing", title="Подписать некому")
    assert (
        await stand.h.process(await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE))
        == "processed"
    )
    [row] = await stand.bell()
    assert (row.tab, row.object_kind, row.object_id) == ("decisions", None, None)
    assert stand.h.bot.sent[-1][1].endswith("https://platform.example.com/admin/signing")


async def test_withdrawn_notice_v2_has_no_link_to_the_hidden_document(stand: Stand) -> None:
    signer, _ = await make_user(stand.h.sessions, "signer2@x.uz", ["admin"])
    await _link(stand.h.sessions, signer.id, 8303, notify_tasks=True)  # итог — класс «задачи»
    data = document_notice(
        [signer.id], kind="letter_sign_withdrawn", title="Письмо отозвано с подписи"
    )
    assert (
        await stand.h.process(await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE_V2))
        == "processed"
    )
    [row] = await stand.bell()
    assert (row.kind, row.tab, row.object_kind, row.object_id) == (
        "eds.letter_sign_withdrawn",
        "system",
        None,
        None,
    )
    assert "http" not in stand.h.bot.sent[-1][1]


async def test_document_notice_repeated_delivery_gives_one_notification(stand: Stand) -> None:
    author, _ = await make_user(stand.h.sessions, "author3@x.uz", ["manager"])
    event_id = str(uuid.uuid4())
    data = document_notice([author.id])
    await stand.receive(data, event_id=event_id, event_type=DOCUMENT_NOTICE_TYPE)
    await stand.receive(data, event_id=event_id, event_type=DOCUMENT_NOTICE_TYPE)
    assert await stand.h.process(event_id) == "processed"
    await stand.h.process(event_id)
    assert len(await stand.bell()) == 1


async def test_document_notice_failed_processing_leaves_nothing(
    stand: Stand, monkeypatch: pytest.MonkeyPatch
) -> None:
    author, _ = await make_user(stand.h.sessions, "author4@x.uz", ["manager"])
    await _link(stand.h.sessions, author.id, 8304, notify_tasks=True)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("сбой после строки колокольчика")

    monkeypatch.setattr(stand.h.notices, "add", broken)
    event_id = await stand.receive(document_notice([author.id]), event_type=DOCUMENT_NOTICE_TYPE)
    assert await stand.h.process(event_id) != "processed"
    assert await stand.bell() == []
    assert stand.h.bot.sent == []


APPROVAL_ID = "6b1d0e2a-4c7f-4a39-8f15-3e9a7c2d5b40"


def task_notice(recipients: list[int], **over: Any) -> dict[str, Any]:
    """Тело `document.notice_requested.v2` (ГЛ-2): КП на одобрение, объект — маршрут."""
    return {
        "notice_key": f"approval:{APPROVAL_ID}:s1:approve_quote",
        "kind": "approve_quote",
        "recipients": recipients,
        "title": "КП на одобрение: КП-0042 v2",
        "subtitle": "ЗВ-2026-104",
        "approval": {"eds_approval_id": APPROVAL_ID, "template": "quote", "number": "КП-0042"},
        "actor": {"type": "system"},
        **over,
    }


async def test_decision_task_goes_to_bell_and_to_telegram_by_default(stand: Stand) -> None:
    director, _ = await make_user(stand.h.sessions, "dir@x.uz", ["manager"])
    await _link(stand.h.sessions, director.id, 8401)

    event_id = await stand.receive(task_notice([director.id]), event_type=DOCUMENT_NOTICE_TYPE_V2)
    assert await stand.h.process(event_id) == "processed"

    [row] = await stand.bell()
    assert (row.kind, row.tab, row.object_kind, row.object_id, row.object_number) == (
        "eds.approve_quote",
        "decisions",
        "approval",
        APPROVAL_ID,
        "КП-0042",
    )
    [(chat, text)] = stand.h.bot.sent
    assert chat == 8401
    assert text.endswith(
        "https://platform.example.com/eds/drafts/%D0%9A%D0%9F-0042?panel=open&tab=approve"
    )


async def test_decisions_switch_off_leaves_only_the_bell(stand: Stand) -> None:
    director, _ = await make_user(stand.h.sessions, "dir2@x.uz", ["manager"])
    await _link(stand.h.sessions, director.id, 8402, notify_decisions=False)

    event_id = await stand.receive(task_notice([director.id]), event_type=DOCUMENT_NOTICE_TYPE_V2)
    assert await stand.h.process(event_id) == "processed"

    assert len(await stand.bell()) == 1  # строка колокольчика не зависит от переключателя
    assert stand.h.bot.sent == []


async def test_other_tasks_reach_telegram_only_when_the_profile_asks(stand: Stand) -> None:
    quiet, _ = await make_user(stand.h.sessions, "quiet@x.uz", ["manager"])
    loud, _ = await make_user(stand.h.sessions, "loud@x.uz", ["manager"])
    await _link(stand.h.sessions, quiet.id, 8403)  # notify_tasks по умолчанию выключен
    await _link(stand.h.sessions, loud.id, 8404, notify_tasks=True)

    event_id = await stand.receive(notice([quiet.id, loud.id]))  # поручение — не решение
    assert await stand.h.process(event_id) == "processed"

    assert len(await stand.bell()) == 2
    assert [chat for chat, _ in stand.h.bot.sent] == [8404]


async def test_rework_is_bell_only_even_when_every_switch_is_on(stand: Stand) -> None:
    author, _ = await make_user(stand.h.sessions, "rework@x.uz", ["manager"])
    await _link(stand.h.sessions, author.id, 8405, notify_tasks=True, notify_decisions=True)
    data = document_notice(
        [author.id],
        kind="rework_document",
        title="Доработайте: Служебка MEMO-2026/014",
        subtitle="Вернул Рустам Директоров: Уточните сумму",
    )
    event_id = await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE_V2)
    assert await stand.h.process(event_id) == "processed"

    [row] = await stand.bell()
    assert (row.kind, row.tab, row.object_kind) == ("eds.rework_document", "decisions", "document")
    assert stand.h.bot.sent == []


async def test_inbound_letter_resolution_task_links_to_the_letter(stand: Stand) -> None:
    director, _ = await make_user(stand.h.sessions, "dir3@x.uz", ["manager"])
    await _link(stand.h.sessions, director.id, 8406)
    data = {
        "notice_key": f"letter:{LETTER_ID}:resolve_letter",
        "kind": "resolve_letter",
        "recipients": [director.id],
        "title": "Наложите резолюцию: ВХ-112/26",
        "subtitle": "ГНК · Требование о пояснениях",
        "letter": {"eds_letter_id": LETTER_ID, "number": "ВХ-112/26", "subject": "Требование"},
        "actor": {"type": "staff", "crm_user_id": 4},
    }
    event_id = await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE_V2)
    assert await stand.h.process(event_id) == "processed"

    [row] = await stand.bell()
    assert (row.kind, row.object_kind, row.object_id, row.object_number) == (
        "eds.resolve_letter",
        "letter",
        LETTER_ID,
        "ВХ-112/26",
    )
    [(chat, text)] = stand.h.bot.sent
    assert chat == 8406
    assert text.endswith(f"https://platform.example.com/eds/tasks/{LETTER_ID}")


async def test_approval_reminder_v2_is_a_decision_for_the_approver(stand: Stand) -> None:
    """ГЛ-1: «Напомнить» по маршруту — уведомление в «Решения» тому, кто согласует (v2 события)."""
    approver, _ = await make_user(stand.h.sessions, "approver@x.uz", ["admin"])
    data = document_notice(
        [approver.id],
        notice_key=f"approval:{DOC_ID}:reminded:1",
        kind="approval_reminder",
        title="Напоминание: нужно ваше решение",
    )
    event_id = await stand.receive(data, event_type=DOCUMENT_NOTICE_TYPE_V2)
    assert await stand.h.process(event_id) == "processed"
    [row] = await stand.bell()
    assert (row.user_id, row.kind, row.tab) == (approver.id, "eds.approval_reminder", "decisions")


async def test_test_company_notice_goes_only_to_those_who_show_test(stand: Stand) -> None:
    """ТЕСТ-2: шлюз — колокольчик и Telegram по тестовой компании только с включённым показом."""
    sessions = stand.h.sessions
    on, _ = await make_user(sessions, "on@x.uz", ["manager"])
    off, _ = await make_user(sessions, "off@x.uz", ["manager"])
    for user, tg in ((on, 8201), (off, 8202)):
        await _link(sessions, user.id, tg, notify_tasks=True)
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == on.id).values(show_test=True))

    event_id = await stand.receive(notice([on.id, off.id], is_test=True))
    assert await stand.h.process(event_id) == "processed"
    assert [r.user_id for r in await stand.bell()] == [on.id]
    assert [chat for chat, _text in stand.h.bot.sent] == [8201]

    # рабочая запись — всем, как раньше
    event_id = await stand.receive(notice([on.id, off.id]))
    assert await stand.h.process(event_id) == "processed"
    assert sorted(r.user_id for r in await stand.bell()) == sorted([on.id, on.id, off.id])
