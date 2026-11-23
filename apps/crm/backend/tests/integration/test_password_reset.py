"""«Забыли пароль?» на реальной БД (W15-H6): ответ одинаков, лимит, один токен — один раз."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import password_reset as rules
from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.main import create_app
from app.models.auth import AuditLog, PasswordResetToken, RefreshToken, User
from app.security.passwords import hash_password, verify_password
from app.services.password_reset import PasswordResetService
from tests.integration.crm_helpers import PASSWORD, FakeSender, login, make_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
PLATFORM = "https://platform.example.com"
NEW_PASSWORD = "Brand-new-secret-77"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeMail:
    def __init__(self, *, ready: bool = True, fails: bool = False) -> None:
        self.ready, self.fails = ready, fails
        self.sent: list[dict[str, Any]] = []

    async def ensure_configured(self) -> None:
        if not self.ready:
            raise ConflictError("no smtp", reason=Reason.SMTP_NOT_CONFIGURED)

    async def send(self, template: str, to: str, context: Any, **kwargs: Any) -> Any:
        if self.fails:
            raise ConflictError("smtp down", reason=Reason.SMTP_UNAVAILABLE)
        self.sent.append({"template": template, "to": to, "context": dict(context), **kwargs})
        return SimpleNamespace(id=1)


class FakeSettings:
    async def get(self) -> Any:
        return SimpleNamespace(company=SimpleNamespace(name="RailTech"))


def make(
    sessions: async_sessionmaker[AsyncSession],
    mail: FakeMail | None = None,
    bot: FakeSender | None = None,
    url: str | None = PLATFORM,
) -> tuple[PasswordResetService, FakeMail, FakeSender | None, Clock]:
    mail = mail or FakeMail()
    clock = Clock()

    async def provider() -> Any:
        return bot

    service = PasswordResetService(sessions, mail, FakeSettings(), provider, url, clock)  # type: ignore[arg-type]
    return service, mail, bot, clock


async def tokens(sessions: async_sessionmaker[AsyncSession]) -> list[PasswordResetToken]:
    async with sessions() as session:
        return list(await session.scalars(select(PasswordResetToken).order_by("id")))


def token_in(link: str) -> str:
    return link.split("token=", 1)[1]


async def test_mail_link_is_sent_and_stored_as_hash(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, mail, _, _ = make(sessions)
    _manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request(" Dilshod@Railtech.uz ")
    ((sent),) = mail.sent
    assert sent["template"] == "password_reset_link"
    assert sent["to"] == "dilshod@railtech.uz"
    link = sent["context"]["reset_url"]
    assert link.startswith(f"{PLATFORM}/reset-password?token=")
    ((row),) = await tokens(sessions)
    assert row.token_hash == rules.hash_token(token_in(link))
    assert row.channel == "email"
    assert row.expires_at - row.created_at == rules.TOKEN_TTL
    assert token_in(link) not in row.token_hash


async def test_unknown_inactive_and_no_channel_do_nothing_quietly(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, mail, _, _ = make(sessions, FakeMail(ready=False))  # нет ни почты, ни Telegram
    quiet, _ = await make_user(sessions, "quiet@railtech.uz", ["manager"])
    gone, _ = await make_user(sessions, "gone@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == gone.id).values(is_active=False))
    for who in ("nobody@railtech.uz", "gone@railtech.uz", "quiet@railtech.uz", "  "):
        await service.request(who)  # исключений нет: ответ одинаков для любого ввода
    assert mail.sent == []
    assert await tokens(sessions) == []
    assert quiet.id


async def test_telegram_is_used_when_there_is_no_mail(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    bot = FakeSender()
    service, mail, _, _ = make(sessions, FakeMail(ready=False), bot)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    assert bot.sent == []
    assert mail.sent == []

    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == manager.id).values(tg_user_id=9001))
    await service.request("dilshod@railtech.uz")
    ((chat, text),) = bot.sent
    assert chat == 9001
    assert f"{PLATFORM}/reset-password?token=" in text
    assert [t.channel for t in await tokens(sessions)] == ["telegram"]


async def test_failed_mail_falls_back_to_telegram_or_discards_the_token(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    bot = FakeSender()
    service, _, _, _ = make(sessions, FakeMail(fails=True), bot)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    assert bot.sent == []
    assert await tokens(sessions) == []

    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == manager.id).values(tg_user_id=9001))
    await service.request("dilshod@railtech.uz")
    assert len(bot.sent) == 1
    assert [t.channel for t in await tokens(sessions)] == ["telegram"]


async def test_no_platform_url_means_no_link(sessions: async_sessionmaker[AsyncSession]) -> None:
    service, mail, _, _ = make(sessions, url=None)
    await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    assert mail.sent == []
    assert await tokens(sessions) == []


async def test_rate_limit_is_three_per_hour(sessions: async_sessionmaker[AsyncSession]) -> None:
    service, mail, _, clock = make(sessions)
    await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    for _ in range(5):
        await service.request("dilshod@railtech.uz")
    assert len(mail.sent) == rules.MAX_REQUESTS_PER_HOUR
    clock.now = NOW + rules.WINDOW + timedelta(minutes=1)  # час прошёл — снова можно
    await service.request("dilshod@railtech.uz")
    assert len(mail.sent) == rules.MAX_REQUESTS_PER_HOUR + 1


async def test_reset_sets_password_once_and_closes_sessions(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    service, mail, _, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as client:
        login(client, manager.email, PASSWORD)  # живая сессия сотрудника (refresh-токен)
    await service.request("dilshod@railtech.uz")
    await service.request("dilshod@railtech.uz")
    first, second = (token_in(m["context"]["reset_url"]) for m in mail.sent)

    await service.reset(first, NEW_PASSWORD)
    async with sessions() as session:
        user = await session.get(User, manager.id)
        assert user is not None
        assert verify_password(user.password_hash, NEW_PASSWORD)
        assert not user.must_change_password
        assert user.failed_logins == 0
        revoked = await session.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == manager.id, RefreshToken.revoked_at.is_(None))
        )
        actions = list(await session.scalars(select(AuditLog.action)))
    assert revoked == 0
    assert "user.password_reset_link" in actions

    # Повтор той же ссылки и вторая, выпущенная раньше сброса, — отказ.
    for used in (first, second):
        with pytest.raises(ValidationFailedError) as caught:
            await service.reset(used, "Another-secret-88")
        assert caught.value.details["reason"] == "reset_token_invalid"


async def test_expired_and_unknown_tokens_are_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, mail, _, clock = make(sessions)
    await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    token = token_in(mail.sent[0]["context"]["reset_url"])
    clock.now = NOW + rules.TOKEN_TTL
    for bad in (token, rules.new_token()):
        with pytest.raises(ValidationFailedError) as caught:
            await service.reset(bad, NEW_PASSWORD)
        assert caught.value.details["reason"] == "reset_token_invalid"


async def test_weak_password_keeps_the_link_usable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, mail, _, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    token = token_in(mail.sent[0]["context"]["reset_url"])
    with pytest.raises(ValidationFailedError) as caught:
        await service.reset(token, "short")
    assert caught.value.details["reason"] == "weak_password"
    await service.reset(token, NEW_PASSWORD)  # ссылка не сгорела
    assert manager.id


@pytest.fixture
def client(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def test_api_answer_is_identical_for_known_and_unknown_accounts(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    known = client.post("/api/v1/auth/forgot-password", json={"identifier": "dilshod@railtech.uz"})
    unknown = client.post("/api/v1/auth/forgot-password", json={"identifier": "nobody@railtech.uz"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 202


async def test_api_reset_with_a_bad_token_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": rules.new_token(), "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "reset_token_invalid"


async def test_background_failure_never_reaches_the_caller(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Выпуск идёт после ответа клиенту: сбой (упал провайдер бота) — в журнал, не наружу."""

    async def broken() -> Any:
        raise RuntimeError("bot provider down")

    service = PasswordResetService(
        sessions,
        FakeMail(),  # type: ignore[arg-type]
        FakeSettings(),  # type: ignore[arg-type]
        broken,
        PLATFORM,
    )
    await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await service.request("dilshod@railtech.uz")
    assert await tokens(sessions) == []


async def test_reset_by_link_closes_sessions_issued_before_it(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> None:
    """Живой access-токен (и сессия в BFF) после сброса не принимается; новый вход работает."""
    service, mail, _, _ = make(sessions)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    with TestClient(create_app(live_settings)) as client:
        old = login(client, manager.email, PASSWORD)
        assert client.get("/api/v1/me", headers=old).status_code == 200
        await service.request("dilshod@railtech.uz")
        await service.reset(token_in(mail.sent[0]["context"]["reset_url"]), NEW_PASSWORD)
        assert client.get("/api/v1/me", headers=old).status_code == 401
        fresh = login(client, manager.email, NEW_PASSWORD)
        assert client.get("/api/v1/me", headers=fresh).status_code == 200


async def test_young_self_linked_telegram_gets_no_reset_link(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Захваченная сессия не должна привязать «свой» Telegram и сразу забрать пароль."""
    bot = FakeSender()
    service, mail, _, clock = make(sessions, FakeMail(ready=False), bot)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id == manager.id)
            .values(tg_user_id=9001, tg_linked_at=NOW - timedelta(hours=2))
        )
    await service.request("dilshod@railtech.uz")
    assert bot.sent == []
    assert await tokens(sessions) == []

    clock.now = NOW + timedelta(hours=23)  # привязке исполнились сутки
    await service.request("dilshod@railtech.uz")
    assert len(bot.sent) == 1
    assert mail.sent == []


async def test_young_telegram_is_not_a_fallback_when_mail_fails(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    bot = FakeSender()
    service, _, _, _ = make(sessions, FakeMail(fails=True), bot)
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id == manager.id)
            .values(tg_user_id=9001, tg_linked_at=NOW - timedelta(hours=1))
        )
    await service.request("dilshod@railtech.uz")
    assert bot.sent == []
    assert await tokens(sessions) == []


# --- ДВ-7: ссылка приглашения и сброса от администратора ---------------------------------------


async def admin_link(
    sessions: async_sessionmaker[AsyncSession], user_id: int, method: str = "invite"
) -> str:
    """Выпустить ссылку как администратор и вернуть токен из «письма»."""
    from app.security.audit import Actor
    from app.services.user_invites import UserInviteService

    mail = FakeMail()
    service = UserInviteService(sessions, mail, FakeSettings(), PLATFORM)  # type: ignore[arg-type]
    await getattr(service, method if method == "invite" else "reset_password_email")(
        Actor(user_id=1), user_id
    )
    (sent,) = mail.sent
    assert "temporary_password" not in sent["context"]
    return token_in(sent["context"]["set_password_url"])


async def test_invite_link_lives_72_hours_and_burns_on_use(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, _, _, clock = make(sessions)
    invited, _ = await make_user(sessions, "aziz@railtech.uz", ["manager"])
    token = await admin_link(sessions, invited.id)
    ((row),) = await tokens(sessions)
    assert row.token_hash == rules.hash_token(token) != token
    assert row.expires_at - row.created_at == rules.INVITE_TTL == timedelta(hours=72)

    clock.now = row.created_at + timedelta(hours=72, minutes=1)
    with pytest.raises(ValidationFailedError):
        await service.reset(token, NEW_PASSWORD)  # просроченная ссылка

    clock.now = row.created_at + timedelta(hours=71)
    await service.reset(token, NEW_PASSWORD)
    with pytest.raises(ValidationFailedError):
        await service.reset(token, NEW_PASSWORD)  # одноразовая
    async with sessions() as session:
        user = await session.get(User, invited.id)
        actions = list(await session.scalars(select(AuditLog.action)))
    assert user is not None
    assert verify_password(user.password_hash, NEW_PASSWORD)
    assert user.must_change_password is False
    assert {"user.invite", "user.password_reset_link"} <= set(actions)


async def test_admin_reset_link_lives_one_hour_and_a_new_link_voids_the_old(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service, _, _, clock = make(sessions)
    manager, old_password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    first = await admin_link(sessions, manager.id, "reset")
    second = await admin_link(sessions, manager.id, "reset")
    rows = await tokens(sessions)
    assert rows[1].expires_at - rows[1].created_at == rules.TOKEN_TTL
    with pytest.raises(ValidationFailedError):
        await service.reset(first, NEW_PASSWORD)  # прежняя ссылка погашена новой
    async with sessions() as session:
        user = await session.get(User, manager.id)
    assert user is not None
    assert not verify_password(user.password_hash, old_password)  # прежний пароль закрыт
    clock.now = rows[1].created_at + timedelta(hours=1, minutes=5)
    with pytest.raises(ValidationFailedError):
        await service.reset(second, NEW_PASSWORD)


async def test_admin_links_are_rate_limited_per_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.domain.errors import RateLimitedError

    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    for _ in range(rules.MAX_REQUESTS_PER_HOUR):
        await admin_link(sessions, manager.id)
    with pytest.raises(RateLimitedError):
        await admin_link(sessions, manager.id)


async def test_unused_set_password_links_die_with_the_old_password_or_the_account(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A link left in the mailbox must not outlive an on-screen reset, a self-change or a block."""
    from app.security.audit import Actor
    from app.services.user_views import UserPatch
    from app.services.users import UserService

    users = UserService(sessions)

    async def open_links(user_id: int) -> int:
        async with sessions() as session:
            return len(
                list(
                    await session.scalars(
                        select(PasswordResetToken).where(
                            PasswordResetToken.user_id == user_id,
                            PasswordResetToken.used_at.is_(None),
                        )
                    )
                )
            )

    onscreen, _ = await make_user(sessions, "umid@railtech.uz", ["manager"])
    await admin_link(sessions, onscreen.id)
    assert await open_links(onscreen.id) == 1
    await users.reset_password(Actor(user_id=1), onscreen.id)
    assert await open_links(onscreen.id) == 0

    own, password = await make_user(sessions, "zafar@railtech.uz", ["manager"])
    await admin_link(sessions, own.id)
    async with (
        sessions() as session,
        session.begin(),
    ):  # restore the old password
        await session.execute(
            update(User).where(User.id == own.id).values(password_hash=hash_password(password))
        )
    await users.change_password(Actor(user_id=own.id), own.id, password, NEW_PASSWORD)
    assert await open_links(own.id) == 0

    blocked, _ = await make_user(sessions, "sanjar@railtech.uz", ["manager"])
    await admin_link(sessions, blocked.id)
    await users.update(Actor(user_id=1), blocked.id, UserPatch(is_active=False))
    assert await open_links(blocked.id) == 0
