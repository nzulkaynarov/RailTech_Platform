"""«Пригласить» и «Сбросить пароль по почте» (M3-CRM-08, ДВ-7): в письме ссылка, пароля нет."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from app.domain import password_reset as rules
from app.domain.errors import ConflictError, NotFoundError, RateLimitedError, Reason
from app.security.audit import Actor
from app.security.passwords import hash_password, verify_password
from app.services import user_invites as svc

OLD_PASSWORD = "Old-password-42"
ACTOR = Actor(user_id=1)
PLATFORM = "https://platform.example.com"


class FakeSession:
    """Сессия без БД: считает уже выпущенные ссылки и запоминает добавленные и погашенные."""

    recent = 0
    added: ClassVar[list[Any]] = []
    voided = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def scalar(self, _statement: Any) -> int:
        return FakeSession.recent

    async def execute(self, _statement: Any) -> None:
        FakeSession.voided += 1

    def add(self, row: Any) -> None:
        FakeSession.added.append(row)


def fake_sessions() -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    return factory


class FakeMail:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.sent: list[dict[str, Any]] = []

    async def ensure_configured(self) -> None:
        if not self.configured:
            raise ConflictError("not configured", reason=Reason.SMTP_NOT_CONFIGURED)

    async def send(self, template: str, to: str, context: Any, **kwargs: Any) -> Any:
        self.sent.append({"template": template, "to": to, "context": dict(context), **kwargs})
        return SimpleNamespace(id=9, to_email=to, status="queued")


class FakeSettings:
    async def get(self) -> Any:
        return SimpleNamespace(
            company=SimpleNamespace(name="RailTech", crm_base_url="https://crm.example.com/")
        )


def make_service(mail: FakeMail, platform_url: str | None = PLATFORM) -> svc.UserInviteService:
    return svc.UserInviteService(
        fake_sessions(),
        mail,  # type: ignore[arg-type]
        FakeSettings(),  # type: ignore[arg-type]
        platform_url,
    )


@pytest.fixture
def user(monkeypatch: pytest.MonkeyPatch) -> Any:
    FakeSession.recent, FakeSession.added, FakeSession.voided = 0, [], 0
    account = SimpleNamespace(
        language="ru",
        id=7,
        email="aziz@railtech.uz",
        full_name="Азиз",
        password_hash=hash_password(OLD_PASSWORD),
        must_change_password=False,
        failed_logins=3,
        locked_until=None,
    )
    audits: list[tuple[str, int]] = []
    revoked: list[int] = []

    async def get_user(session: Any, user_id: int, **_: Any) -> Any:
        return account if user_id == account.id else None

    async def record(
        session: Any, actor: Actor, action: str, _t: str, entity_id: int, **_: Any
    ) -> None:
        audits.append((action, entity_id))

    async def revoke(session: Any, user_id: int) -> None:
        revoked.append(user_id)

    monkeypatch.setattr("app.services.user_invites.repo.get", get_user)
    monkeypatch.setattr("app.services.user_invites.audit.record", record)
    monkeypatch.setattr("app.services.user_invites.close_sessions", revoke)
    account.audits, account.revoked = audits, revoked
    return account


@pytest.mark.parametrize(
    ("method", "template", "action", "ttl"),
    [
        ("invite", "invite", "user.invite", rules.INVITE_TTL),
        ("reset_password_email", "password_reset", "user.reset_password_email", rules.TOKEN_TTL),
    ],
)
async def test_sends_one_time_link_and_never_a_password(
    user: Any, method: str, template: str, action: str, ttl: Any
) -> None:
    mail = FakeMail()
    service = make_service(mail)
    view = await getattr(service, method)(ACTOR, 7)
    assert view.id == 9
    (letter,) = mail.sent
    assert (letter["template"], letter["to"], letter["user_id"], letter["requested_by"]) == (
        template,
        "aziz@railtech.uz",
        7,
        1,
    )
    context = letter["context"]
    # Ссылка ведёт в Платформу, а не в старый фронт CRM (`company.crm_base_url`), W15-H8a.
    assert context["set_password_url"].startswith(f"{PLATFORM}/reset-password?token=")
    assert "crm_url" not in context
    assert context["company"] == "RailTech"
    # ДВ-7: пароля в письме нет — ни в значениях, ни под другим ключом.
    assert "temporary_password" not in context
    assert "password" not in {key.lower() for key in context}
    # Токен: в письме открытый, в базе — только хеш; срок по виду письма; прежние ссылки погашены.
    token = context["set_password_url"].split("token=")[1]
    (row,) = FakeSession.added
    assert row.token_hash == rules.hash_token(token)
    assert token not in vars(row).values()
    assert row.channel == "email"
    assert row.expires_at - row.created_at == ttl
    assert FakeSession.voided == 1
    # Прежний пароль больше не действует, нового никто не знает; статус — «Приглашён».
    assert not verify_password(user.password_hash, OLD_PASSWORD)
    assert (user.must_change_password, user.failed_logins) == (True, 0)
    assert user.audits == [(action, 7)]
    assert user.revoked == [7]


@pytest.mark.parametrize("method", ["invite", "reset_password_email"])
async def test_link_requests_are_rate_limited_per_account(user: Any, method: str) -> None:
    FakeSession.recent = rules.MAX_REQUESTS_PER_HOUR
    mail = FakeMail()
    with pytest.raises(RateLimitedError):
        await getattr(make_service(mail), method)(ACTOR, 7)
    assert mail.sent == []
    assert FakeSession.added == []
    assert (user.audits, user.revoked) == ([], [])


async def test_without_smtp_password_is_untouched_and_error_is_clear(user: Any) -> None:
    service = make_service(FakeMail(configured=False))
    with pytest.raises(ConflictError) as info:
        await service.invite(ACTOR, 7)
    assert info.value.details["reason"] == Reason.SMTP_NOT_CONFIGURED.value
    assert verify_password(user.password_hash, OLD_PASSWORD)
    assert user.audits == []
    assert user.revoked == []


async def test_unknown_user_is_404(user: Any) -> None:
    service = make_service(FakeMail())
    with pytest.raises(NotFoundError):
        await service.invite(ACTOR, 404)


@pytest.mark.parametrize("method", ["invite", "reset_password_email"])
@pytest.mark.parametrize("platform_url", [None, ""])
async def test_without_platform_url_nothing_is_sent_and_password_is_untouched(
    user: Any, method: str, platform_url: str | None
) -> None:
    """Адреса Платформы нет: честная 409, а не письмо со ссылкой на localhost (W15-H8a)."""
    mail = FakeMail()
    service = make_service(mail, platform_url)
    with pytest.raises(ConflictError) as info:
        await getattr(service, method)(ACTOR, 7)
    assert "PLATFORM_DOMAIN" not in info.value.message  # админу — человеческий текст
    assert "хостинг" in info.value.message
    assert "PLATFORM_DOMAIN" in str(info.value.details["hint"])
    assert mail.sent == []
    assert verify_password(user.password_hash, OLD_PASSWORD)
    assert (user.audits, user.revoked) == ([], [])
