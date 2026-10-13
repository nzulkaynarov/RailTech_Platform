"""Маршрутизация алертов: личка админам → канал как запасной путь; отказ Telegram (Q-010)."""

import contextlib
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError
from app.domain.staff_notify import Staff
from app.services import staff_notifier
from app.services.monitoring import MonitorService
from app.services.settings import SettingsService
from app.services.staff_notifier import StaffNotifier
from app.services.system_status import missing_secrets

CHANNEL = -100500


class FakeBot:
    """Фейковый aiogram Bot: запоминает отправленное, «блокирует» указанные чаты."""

    def __init__(self, blocked: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.blocked = blocked or set()

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        if chat_id in self.blocked:
            raise TelegramForbiddenError(
                SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked by the user"
            )
        self.sent.append((chat_id, text))
        return object()


def fake_sessions() -> async_sessionmaker[AsyncSession]:
    @contextlib.asynccontextmanager
    async def session() -> AsyncIterator[object]:
        yield object()

    return cast(async_sessionmaker[AsyncSession], session)


def admin(uid: int, tg: int | None, *, system: bool = True) -> Staff:
    return Staff(uid, ("admin",), True, tg, system, True)


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch) -> list[Staff]:
    people: list[Staff] = []

    async def fake_staff(_: object, user_id: int | None = None) -> list[Staff]:
        return people

    monkeypatch.setattr(staff_notifier, "_staff", fake_staff)
    return people


def monitor(bot: FakeBot) -> MonitorService:
    async def probe() -> bool:
        return True

    sessions = fake_sessions()
    return MonitorService(sessions, SettingsService(sessions), cast(Bot, bot), probe)


@pytest.mark.parametrize(
    ("admins", "blocked", "expected"),
    [
        ([admin(1, 11)], set(), [11]),
        ([admin(1, 11), admin(2, 22)], set(), [11, 22]),
        ([admin(1, 11), admin(2, 22)], {11}, [22]),
        ([admin(1, 11)], {11}, [CHANNEL]),
        ([admin(1, None)], set(), [CHANNEL]),
        ([admin(1, 11, system=False)], set(), [CHANNEL]),
        ([], set(), [CHANNEL]),
    ],
    ids=["one", "two", "one-blocked", "all-blocked", "no-tg", "unsubscribed", "no-admins"],
)
async def test_alert_goes_to_admins_then_channel(
    team: list[Staff], admins: list[Staff], blocked: set[int], expected: list[int]
) -> None:
    team.extend(admins)
    bot = FakeBot(blocked)
    assert await monitor(bot)._alert(CHANNEL, "⚠️ LiteLLM", "litellm_down") is True
    assert [chat for chat, _ in bot.sent] == expected


async def test_alert_without_channel_and_admins_is_not_delivered(team: list[Staff]) -> None:
    bot = FakeBot()
    assert await monitor(bot)._alert(None, "⚠️", "queue_size") is False
    assert bot.sent == []


async def test_test_message_refused_by_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = StaffNotifier(fake_sessions(), FakeBot(blocked={55}))

    class Session:
        async def scalar(self, _: object) -> int:
            return 55

    @contextlib.asynccontextmanager
    async def sessions() -> AsyncIterator[Session]:
        yield Session()

    notifier._sessions = cast(async_sessionmaker[AsyncSession], sessions)
    with pytest.raises(ConflictError) as err:
        await notifier.test_message(1)
    assert err.value.details["reason"] == "telegram_refused"
    assert "blocked" in str(err.value.details["telegram_error"])


async def test_test_message_without_bot() -> None:
    with pytest.raises(ConflictError) as err:
        await StaffNotifier(fake_sessions(), None).test_message(1)
    assert err.value.details["reason"] == "bot_not_configured"


def test_missing_secrets_names_only() -> None:
    config = Settings(_env_file=None, jwt_secret="x" * 40, telegram_mode="webhook")
    missing = missing_secrets(config)
    assert "JWT_SECRET" not in missing
    assert "TELEGRAM_WEBHOOK_SECRET" in missing
    assert all(name.isupper() for name in missing)
    assert "TELEGRAM_BOT_TOKEN" in missing
    assert "TELEGRAM_BOT_TOKEN" not in missing_secrets(config, token_elsewhere=True)
