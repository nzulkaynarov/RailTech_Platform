"""Обращения сотрудников к администратору и колокольчик CRM на реальной БД (W15-H7)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, NotFoundError, RateLimitedError
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.staff_tickets import StaffNotification
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.staff_notifications import StaffNotificationService
from app.services.staff_tickets import StaffTicketService
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


class FakeMessenger:
    def __init__(self) -> None:
        self.direct_calls: list[tuple[int, str, str]] = []
        self.alerts: list[tuple[str, str]] = []

    async def direct(self, user_id: int, text: str, key: str) -> bool:
        self.direct_calls.append((user_id, text, key))
        return True

    async def alert_admins(self, text: str, key: str) -> int:
        self.alerts.append((text, key))
        return 1


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def svc(
    sessions: async_sessionmaker[AsyncSession],
    messenger: FakeMessenger | None = None,
    now: datetime = NOW,
) -> StaffTicketService:
    async def get() -> FakeMessenger | None:
        return messenger

    return StaffTicketService(sessions, get, "https://platform.example", lambda: now)


async def new_ticket(
    service: StaffTicketService, author_id: int, body: str = "Нужен доступ к «Расчёту»"
) -> int:
    detail = await service.create(
        Actor(author_id),
        author_id,
        subject="access",
        body=body,
        page="/erp/calc",
        role="Менеджер",
    )
    return detail.row.id


async def test_create_keeps_page_role_and_notifies_admins_not_the_author(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    author, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    messenger = FakeMessenger()
    service = svc(sessions, messenger)

    detail = await service.create(
        Actor(author.id),
        author.id,
        subject="access",
        body="  Нужен доступ к «Расчёту»  ",
        page="/erp/calc?panel=open",
        role="Менеджер",
    )

    assert detail.row.number == f"ОБР-{detail.row.id:04d}"
    assert (detail.row.status, detail.row.subject) == ("new", "access")
    assert detail.row.page == "/erp/calc?panel=open"
    assert detail.row.author_role == "Менеджер"
    assert detail.body == "Нужен доступ к «Расчёту»"
    assert detail.messages == []
    bell = await StaffNotificationService(sessions).list(boss.id)
    assert [n.title for n in bell] == [f"Новое обращение {detail.row.number}"]
    assert bell[0].object_kind == "ticket"
    assert bell[0].object_id == str(detail.row.id)
    assert await StaffNotificationService(sessions).list(author.id) == []
    assert [key for _, key in messenger.alerts] == [f"staff_ticket:{detail.row.id}"]
    assert "ОБР-" in messenger.alerts[0][0]
    async with sessions() as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
    assert "staff_ticket.create" in actions


async def test_author_sees_only_own_tickets(sessions: async_sessionmaker[AsyncSession]) -> None:
    a, _ = await make_user(sessions, "alisher@railtech.uz", ["manager"])
    b, _ = await make_user(sessions, "bobur@railtech.uz", ["manager"])
    service = svc(sessions)
    mine = await new_ticket(service, a.id)
    theirs = await new_ticket(service, b.id)

    assert [t.id for t in await service.list_own(a.id)] == [mine]
    assert (await service.get_own(a.id, mine)).row.id == mine
    with pytest.raises(NotFoundError):
        await service.get_own(a.id, theirs)


async def test_rate_limit_is_five_per_hour_per_author(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    a, _ = await make_user(sessions, "alisher@railtech.uz", ["manager"])
    b, _ = await make_user(sessions, "bobur@railtech.uz", ["manager"])
    service = svc(sessions)
    for i in range(5):
        await new_ticket(service, a.id, f"вопрос {i}")
    with pytest.raises(RateLimitedError):
        await new_ticket(service, a.id, "шестой")
    await new_ticket(service, b.id)  # лимит у каждого свой
    later = svc(sessions, now=NOW + timedelta(hours=1, minutes=1))
    await new_ticket(later, a.id, "через час можно")


async def test_reply_takes_new_into_work_and_tells_the_author(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    author, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    messenger = FakeMessenger()
    service = svc(sessions, messenger)
    ticket_id = await new_ticket(service, author.id)

    detail = await service.reply(Actor(boss.id), ticket_id, "Доступ выдан, перезайдите")

    assert detail.row.status == "in_progress"
    assert [(m.body, m.author_name) for m in detail.messages] == [
        ("Доступ выдан, перезайдите", "boss")
    ]
    bell = await StaffNotificationService(sessions).list(author.id)
    assert [n.kind for n in bell] == ["ticket_reply"]
    assert bell[0].title == f"Ответ на обращение {detail.row.number}"
    assert bell[0].subtitle == "Доступ выдан, перезайдите"
    assert bell[0].read is False
    [(user_id, text, key)] = messenger.direct_calls
    assert user_id == author.id
    assert "Доступ выдан" in text
    assert f"https://platform.example/help/requests/{detail.row.number}" in text
    assert key == f"staff_ticket_reply:{ticket_id}"


async def test_reply_with_status_resolves_and_reopen_is_possible(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    author, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = svc(sessions)
    ticket_id = await new_ticket(service, author.id)

    done = await service.reply(Actor(boss.id), ticket_id, "Готово", status="resolved")
    assert done.row.status == "resolved"
    assert done.resolved_at == NOW

    reopened = await service.set_status(Actor(boss.id), ticket_id, "in_progress")
    assert reopened.row.status == "in_progress"
    assert reopened.resolved_at is None
    with pytest.raises(ConflictError):
        await service.set_status(Actor(boss.id), ticket_id, "new")


async def test_status_change_to_resolved_without_reply_notifies_the_author(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    author, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = svc(sessions)
    ticket_id = await new_ticket(service, author.id)

    await service.set_status(Actor(boss.id), ticket_id, "resolved")

    bell = await StaffNotificationService(sessions).list(author.id)
    assert [n.kind for n in bell] == ["ticket_resolved"]
    async with sessions() as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
    assert "staff_ticket.status" in actions


async def test_admin_list_orders_open_first_and_counts_statuses(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    author, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = svc(sessions)
    first = await new_ticket(service, author.id, "первое")
    second = await new_ticket(service, author.id, "второе")
    third = await new_ticket(service, author.id, "третье")
    await service.reply(Actor(boss.id), first, "ок", status="resolved")
    await service.reply(Actor(boss.id), second, "смотрю")

    page = await service.list_all(status=None, subject=None, limit=50, offset=0)

    assert [t.id for t in page.items] == [second, third, first] or [t.id for t in page.items] == [
        third,
        second,
        first,
    ]
    assert page.items[-1].status == "resolved"
    assert page.counts == {"new": 1, "in_progress": 1, "resolved": 1}
    only_new = await service.list_all(status="new", subject=None, limit=50, offset=0)
    assert [t.id for t in only_new.items] == [third]
    assert only_new.total == 1


async def test_notifications_are_private_and_can_be_marked_read(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    a, _ = await make_user(sessions, "alisher@railtech.uz", ["manager"])
    b, _ = await make_user(sessions, "bobur@railtech.uz", ["manager"])
    notes = StaffNotificationService(sessions, lambda: NOW)
    await notes.add([a.id], kind="telegram_linked", tab="system", title="Привязан Telegram")
    await notes.add([a.id, a.id, b.id], kind="ticket_reply", tab="system", title="Ответ")
    mine = await notes.list(a.id)
    assert len(mine) == 2  # дубль получателя в одном вызове схлопывается
    assert await notes.unread_count(a.id) == 2
    assert await notes.unread_count(b.id) == 1

    foreign = (await notes.list(b.id))[0].id
    with pytest.raises(NotFoundError):
        await notes.mark_read(a.id, foreign)
    await notes.mark_read(a.id, mine[0].id)
    assert await notes.unread_count(a.id) == 1
    assert await notes.mark_all_read(a.id) == 1
    assert await notes.unread_count(a.id) == 0
    assert await notes.unread_count(b.id) == 1


async def test_api_author_creates_and_reads_only_own_admin_replies(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    author, author_pw = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    other, other_pw = await make_user(sessions, "other@railtech.uz", ["manager"])
    boss, boss_pw = await make_user(sessions, "boss@railtech.uz", ["admin"])
    mine = login(client, author.email, author_pw)
    theirs = login(client, other.email, other_pw)
    admin = login(client, boss.email, boss_pw)

    created = client.post(
        "/api/v1/me/tickets",
        headers=mine,
        json={
            "subject": "template",
            "body": "Нужен шаблон письма",
            "page": "/eds/new",
            "role": "Менеджер",
        },
    )
    assert created.status_code == 201, created.text
    ticket = created.json()
    assert ticket["status"] == "new"
    ticket_id = ticket["id"]

    assert [t["id"] for t in client.get("/api/v1/me/tickets", headers=mine).json()] == [ticket_id]
    assert client.get("/api/v1/me/tickets", headers=theirs).json() == []
    assert client.get(f"/api/v1/me/tickets/{ticket_id}", headers=theirs).status_code == 404
    # Свои обращения — не раздел админа: список всех и ответ автору недоступны.
    assert client.get("/api/v1/staff-tickets", headers=mine).status_code == 403
    assert (
        client.post(
            f"/api/v1/staff-tickets/{ticket_id}/reply", headers=mine, json={"body": "сам себе"}
        ).status_code
        == 403
    )

    everything = client.get("/api/v1/staff-tickets", headers=admin)
    assert everything.status_code == 200, everything.text
    assert everything.json()["counts"] == {"new": 1, "in_progress": 0, "resolved": 0}
    replied = client.post(
        f"/api/v1/staff-tickets/{ticket_id}/reply",
        headers=admin,
        json={"body": "Шаблон добавлен", "status": "resolved"},
    )
    assert replied.status_code == 200, replied.text
    assert replied.json()["status"] == "resolved"
    assert replied.json()["messages"][0]["body"] == "Шаблон добавлен"

    seen = client.get(f"/api/v1/me/tickets/{ticket_id}", headers=mine).json()
    assert seen["messages"][0]["body"] == "Шаблон добавлен"
    bell = client.get("/api/v1/me/notifications", headers=mine).json()
    assert bell["unread_count"] == 1
    assert bell["items"][0]["kind"] == "ticket_reply"
    note_id = bell["items"][0]["id"]
    assert (
        client.post(f"/api/v1/me/notifications/{note_id}/read", headers=theirs).status_code == 404
    )
    assert client.post(f"/api/v1/me/notifications/{note_id}/read", headers=mine).status_code == 204
    assert client.get("/api/v1/me/notifications", headers=mine).json()["unread_count"] == 0


async def test_api_validation_errors_carry_reason_and_field(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    author, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, author.email, password)
    for payload, reason, field in [
        ({"subject": "bug", "body": "текст"}, "ticket_subject_unknown", "subject"),
        ({"subject": "error", "body": "   "}, "ticket_text_empty", "body"),
        (
            {"subject": "error", "body": "x", "page": "https://evil.example"},
            "ticket_page_invalid",
            "page",
        ),
    ]:
        response = client.post("/api/v1/me/tickets", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        details = response.json()["details"]
        assert (details["reason"], details["field"]) == (reason, field)


async def test_api_rate_limit_returns_429(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    author, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, author.email, password)
    for i in range(5):
        ok = client.post(
            "/api/v1/me/tickets", headers=headers, json={"subject": "other", "body": f"п{i}"}
        )
        assert ok.status_code == 201
    over = client.post(
        "/api/v1/me/tickets", headers=headers, json={"subject": "other", "body": "ещё"}
    )
    assert over.status_code == 429
    assert over.json()["details"]["reason"] == "ticket_rate_limited"


async def test_api_onboarding_flag_is_set_once_by_the_user(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user, password = await make_user(sessions, "new@railtech.uz", ["manager"])
    headers = login(client, user.email, password)

    # Новый сотрудник (создан после раскатки) приветствие ещё не видел.
    async def reset() -> None:
        async with sessions() as session, session.begin():
            row = await session.get(User, user.id)
            assert row is not None
            row.onboarding_done_at = None

    await reset()
    assert client.get("/api/v1/me", headers=headers).json()["onboarding_done"] is False

    done = client.patch("/api/v1/me", headers=headers, json={"onboarding_done": True})
    assert done.status_code == 200, done.text
    assert done.json()["onboarding_done"] is True
    assert (
        client.patch("/api/v1/me", headers=headers, json={"onboarding_done": False}).status_code
        == 422
    )


class MailNotConfigured:
    async def ensure_configured(self) -> None:
        raise ConflictError("mail is not configured")


async def test_telegram_link_adds_a_bell_row_even_without_mail(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.services.staff_link_notice import StaffLinkNotice

    user, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    notice = StaffLinkNotice(
        sessions,
        MailNotConfigured(),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        "https://platform.example",
        StaffNotificationService(sessions),
    )

    await notice.linked(user.id, "dilshod_t")

    async with sessions() as session:
        rows = list((await session.scalars(select(StaffNotification))).all())
    assert [r.kind for r in rows] == ["telegram_linked"]
    assert "@dilshod_t" in rows[0].title
    assert rows[0].object_kind is None


async def test_api_director_reads_tickets_but_cannot_reply_or_change_status(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    author, author_pw = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    account, password = await make_user(sessions, "director@railtech.uz", ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, ["DIRECTOR"])]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    mine = login(client, author.email, author_pw)
    director = login(client, account.email, password)
    ticket_id = client.post(
        "/api/v1/me/tickets", headers=mine, json={"subject": "error", "body": "Ошибка в КП"}
    ).json()["id"]

    assert client.get("/api/v1/staff-tickets", headers=director).status_code == 200
    assert client.get(f"/api/v1/staff-tickets/{ticket_id}", headers=director).status_code == 200
    reply = client.post(
        f"/api/v1/staff-tickets/{ticket_id}/reply", headers=director, json={"body": "Смотрю"}
    )
    assert reply.status_code == 403, reply.text
    status = client.post(
        f"/api/v1/staff-tickets/{ticket_id}/status", headers=director, json={"status": "resolved"}
    )
    assert status.status_code == 403, status.text


async def test_api_too_long_page_is_clipped_not_rejected(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    author, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, author.email, password)
    page = "/eds/inbox/" + "a" * 600
    response = client.post(
        "/api/v1/me/tickets",
        headers=headers,
        json={"subject": "error", "body": "Не открывается", "page": page},
    )
    assert response.status_code == 201, response.text
    assert response.json()["page"] == page[:300]
