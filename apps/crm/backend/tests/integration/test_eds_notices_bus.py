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


async def _link(sessions: async_sessionmaker[AsyncSession], user_id: int, tg: int) -> None:
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == user_id).values(tg_user_id=tg))


async def test_bell_and_telegram_for_each_active_recipient(stand: Stand) -> None:
    sessions = stand.h.sessions
    executor, _ = await make_user(sessions, "exec@x.uz", ["manager"])
    reader, _ = await make_user(sessions, "reader@x.uz", ["manager"])
    gone, _ = await make_user(sessions, "gone@x.uz", ["manager"])
    await _link(sessions, executor.id, 8101)
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
    await _link(stand.h.sessions, executor.id, 8102)

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
