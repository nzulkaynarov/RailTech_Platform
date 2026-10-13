"""«Пригласить» и «Сбросить пароль по почте» (M3-CRM-08): без SMTP пароль не трогаем."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.errors import ConflictError, NotFoundError, Reason
from app.security.audit import Actor
from app.security.passwords import hash_password, verify_password
from app.services import user_invites as svc

OLD_PASSWORD = "Old-password-42"
ACTOR = Actor(user_id=1)


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


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


@pytest.fixture
def user(monkeypatch: pytest.MonkeyPatch) -> Any:
    account = SimpleNamespace(
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
    monkeypatch.setattr("app.services.user_invites.revoke_tokens", revoke)
    account.audits, account.revoked = audits, revoked
    return account


@pytest.mark.parametrize(
    ("method", "template", "action"),
    [
        ("invite", "invite", "user.invite"),
        ("reset_password_email", "password_reset", "user.reset_password_email"),
    ],
)
async def test_rotates_password_and_sends_letter(
    user: Any, method: str, template: str, action: str
) -> None:
    mail = FakeMail()
    service = svc.UserInviteService(fake_sessions(), mail, FakeSettings())  # type: ignore[arg-type]
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
    assert context["crm_url"] == "https://crm.example.com"
    assert context["company"] == "RailTech"
    assert verify_password(user.password_hash, context["temporary_password"])
    assert not verify_password(user.password_hash, OLD_PASSWORD)
    assert (user.must_change_password, user.failed_logins) == (True, 0)
    assert user.audits == [(action, 7)]
    assert user.revoked == [7]


async def test_without_smtp_password_is_untouched_and_error_is_clear(user: Any) -> None:
    service = svc.UserInviteService(fake_sessions(), FakeMail(configured=False), FakeSettings())  # type: ignore[arg-type]
    with pytest.raises(ConflictError) as info:
        await service.invite(ACTOR, 7)
    assert info.value.details["reason"] == Reason.SMTP_NOT_CONFIGURED.value
    assert verify_password(user.password_hash, OLD_PASSWORD)
    assert user.audits == []
    assert user.revoked == []


async def test_unknown_user_is_404(user: Any) -> None:
    service = svc.UserInviteService(fake_sessions(), FakeMail(), FakeSettings())  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.invite(ACTOR, 404)
