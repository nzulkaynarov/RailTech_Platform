"""Письмо «К профилю привязан Telegram» (W15-H6): уходит при настроенной почте, без неё — тихо."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.errors import ConflictError, Reason
from app.services.staff_link_notice import StaffLinkNotice


class Mail:
    def __init__(self, configured: bool) -> None:
        self.configured = configured
        self.sent: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    async def ensure_configured(self) -> None:
        if not self.configured:
            raise ConflictError("no smtp", reason=Reason.SMTP_NOT_CONFIGURED)

    async def send(self, template: str, to: str, context: Any, **kwargs: Any) -> None:
        self.sent.append((template, to, dict(context), kwargs))


class Settings:
    async def get(self) -> Any:
        return SimpleNamespace(company=SimpleNamespace(name="RailTech"))


def notice(mail: Mail, url: str | None, monkeypatch: pytest.MonkeyPatch) -> StaffLinkNotice:
    user = SimpleNamespace(
        id=7, email="aziz@railtech.uz", full_name="Азиз", language="uz", is_active=True
    )

    @asynccontextmanager
    async def sessions() -> Any:
        yield object()

    async def get(_session: Any, user_id: int) -> Any:
        return user if user_id == 7 else None

    monkeypatch.setattr("app.services.staff_link_notice.repo.get", get)
    return StaffLinkNotice(sessions, mail, Settings(), url)  # type: ignore[arg-type]


async def test_mail_names_the_account_and_where_to_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    mail = Mail(True)
    await notice(mail, "https://platform.example.com/", monkeypatch).linked(7, "intruder")
    ((template, to, context, kwargs),) = mail.sent
    assert (template, to) == ("telegram_linked", "aziz@railtech.uz")
    assert context["account"] == "@intruder"
    assert context["profile_url"] == "https://platform.example.com/me"
    assert kwargs["lang"] == "uz"


async def test_without_mail_or_user_nothing_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    mail = Mail(False)
    await notice(mail, None, monkeypatch).linked(7, None)
    assert mail.sent == []
    mail = Mail(True)
    await notice(mail, None, monkeypatch).linked(99, None)
    assert mail.sent == []


async def test_without_platform_url_the_mail_still_says_where(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = Mail(True)
    await notice(mail, None, monkeypatch).linked(7, None)
    assert mail.sent[0][2]["profile_url"] == "Платформа → Профиль"
    assert mail.sent[0][2]["account"] == ""
