"""«Подключения»: пароль обязателен, неверный токен не сохраняется, токен не уходит в аудит/логи."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.bot.profile import ProfilePublish
from app.domain.errors import (
    AccountLockedError,
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.telegram import (
    BotIdentity,
    InvalidBotTokenError,
    TelegramUnavailableError,
)
from app.schemas.integrations import TelegramStatusOut, TelegramTokenIn
from app.schemas.settings_profile import BotProfileSettings
from app.security.passwords import hash_password
from app.security.principal import Principal
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services import integrations as svc
from app.services.bot_state import BotSnapshot

TOKEN = "123456:fake-token-for-unit-tests-AbCd"
PASSWORD = "admin-pass-123"
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


def fake_sessions() -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    return factory


class FakeStore(SecretsStore):
    def __init__(self, *, enabled: bool = True) -> None:
        cipher = SecretCipher(secrets.token_hex(32)) if enabled else None
        super().__init__(fake_sessions(), cipher)
        self.saved: dict[str, str] = {}

    async def put(self, session: Any, key: str, value: str, user_id: int | None) -> None:
        self.saved[key] = value

    async def status(self, key: str) -> None:
        return None


class FakeProbe:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def get_me(self, token: str) -> BotIdentity:
        self.calls.append(token)
        if self.error is not None:
            raise self.error
        return BotIdentity(id=42, username="railtech_test_bot")


class FakeBot:
    """`crm-bot` со стороны API: что он сообщил в БД и что у него просили (`BotLink`)."""

    def __init__(self, snapshot: BotSnapshot | None = None, *, applied: bool = True) -> None:
        self.state = snapshot if snapshot is not None else SNAPSHOT
        self.applied = applied
        self.restarts = 0
        self.waits: list[float] = []
        self.profile: ProfilePublish | None = None

    async def snapshot(self) -> BotSnapshot | None:
        return self.state

    async def request_restart(self, session: Any) -> datetime:
        self.restarts += 1
        return REQUESTED

    async def wait_applied(self, requested_at: datetime, timeout_s: float) -> bool:
        self.waits.append(timeout_s)
        return self.applied

    async def record_profile(self, result: ProfilePublish) -> None:
        self.profile = result


REQUESTED = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
SNAPSHOT = BotSnapshot(
    alive=True,
    running=True,
    source="db",
    username="railtech_test_bot",
    mode="polling",
    last_error=None,
    profile=None,
    heartbeat_age_s=1.0,
)


class FakeSettings:
    async def get(self) -> Any:
        return SimpleNamespace(notifications=SimpleNamespace(channel_id=None))


@pytest.fixture
def audit_log(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    async def record(*args: Any, **kwargs: Any) -> None:
        records.append({"args": args, **kwargs})

    user = SimpleNamespace(
        id=0, password_hash=hash_password(PASSWORD), failed_logins=0, locked_until=None
    )

    async def get_user(session: Any, user_id: int, **_: Any) -> Any:
        user.id = user_id
        return user

    monkeypatch.setattr("app.services.integrations.audit.record", record)
    monkeypatch.setattr("app.services.integrations.users_repo.get", get_user)
    return records


def make(
    probe: FakeProbe, store: FakeStore, bot: FakeBot | None = None
) -> svc.TelegramIntegrationService:
    async def no_bot() -> None:
        return None

    return svc.TelegramIntegrationService(
        fake_sessions(),
        FakeSettings(),  # type: ignore[arg-type]
        store,
        probe,
        bot or FakeBot(),
        no_bot,
        mode="polling",
        restart_wait_s=3.0,
    )


async def test_wrong_password_rejected_before_telegram(audit_log: list[dict[str, Any]]) -> None:
    probe, store = FakeProbe(), FakeStore()
    with pytest.raises(ValidationFailedError) as caught:
        await make(probe, store).save_token(ADMIN, TOKEN, "wrong-password-1")
    assert caught.value.details["reason"] == Reason.WRONG_PASSWORD
    assert probe.calls == []
    assert store.saved == {}
    assert audit_log == []


@pytest.mark.parametrize(
    ("error", "exc_type", "reason"),
    [
        (InvalidBotTokenError("401"), ValidationFailedError, Reason.INVALID_BOT_TOKEN),
        (TelegramUnavailableError("net"), UpstreamUnavailableError, Reason.TELEGRAM_UNAVAILABLE),
    ],
)
async def test_failed_check_does_not_save(
    audit_log: list[dict[str, Any]], error: Exception, exc_type: type[Exception], reason: Reason
) -> None:
    probe, store, bot = FakeProbe(error), FakeStore(), FakeBot()
    with pytest.raises(exc_type) as caught:
        await make(probe, store, bot).save_token(ADMIN, TOKEN, PASSWORD)
    assert caught.value.details["reason"] == reason  # type: ignore[attr-defined]
    assert store.saved == {}
    assert audit_log == []
    assert bot.restarts == 0


async def test_store_disabled_without_secrets_key(audit_log: list[dict[str, Any]]) -> None:
    with pytest.raises(ConflictError) as caught:
        await make(FakeProbe(), FakeStore(enabled=False)).save_token(ADMIN, TOKEN, PASSWORD)
    assert caught.value.details["reason"] == Reason.SECRETS_KEY_MISSING


async def test_success_saves_audits_without_value_and_restarts(
    audit_log: list[dict[str, Any]],
) -> None:
    probe, store, bot = FakeProbe(), FakeStore(), FakeBot()
    with capture_logs() as logs:
        identity = await make(probe, store, bot).save_token(ADMIN, f"  {TOKEN} ", PASSWORD)
    assert identity.username == "railtech_test_bot"
    assert store.saved == {"telegram_bot_token": TOKEN}
    assert bot.restarts == 1  # запрос в БД; сам перезапуск делает crm-bot
    assert bot.waits == [3.0]
    assert len(audit_log) == 1
    assert TOKEN not in repr(audit_log)
    assert audit_log[0]["after"]["last4"] == "AbCd"
    assert TOKEN not in repr(logs)
    assert PASSWORD not in repr(logs)


async def test_save_does_not_fail_when_crm_bot_is_slow(audit_log: list[dict[str, Any]]) -> None:
    """crm-bot лежит или занят: токен сохранён, админ получает ответ, предупреждение — в журнале."""
    probe, store, bot = FakeProbe(), FakeStore(), FakeBot(applied=False)
    with capture_logs() as logs:
        identity = await make(probe, store, bot).save_token(ADMIN, TOKEN, PASSWORD)
    assert identity.username == "railtech_test_bot"
    assert store.saved == {"telegram_bot_token": TOKEN}
    assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
        "bot_restart_not_confirmed"
    ]


@pytest.mark.parametrize(
    ("snapshot", "running", "error"),
    [
        (SNAPSHOT, True, None),
        (replace(SNAPSHOT, alive=False, running=False), False, "bot_process_down"),
        (
            replace(SNAPSHOT, running=False, last_error="TelegramNetworkError"),
            False,
            "TelegramNetworkError",
        ),
    ],
)
async def test_status_comes_from_crm_bot_record(
    snapshot: BotSnapshot, running: bool, error: str | None
) -> None:
    status = await make(FakeProbe(), FakeStore(), FakeBot(snapshot)).status()
    assert (status.running, status.last_error) == (running, error)


async def test_status_before_crm_bot_ever_reported() -> None:
    bot = FakeBot()
    bot.state = None  # type: ignore[assignment]
    status = await make(FakeProbe(), FakeStore(), bot).status()
    assert (status.running, status.last_error) == (False, "bot_process_never_started")
    assert status.username is None


async def test_status_never_contains_token(audit_log: list[dict[str, Any]]) -> None:
    status = await make(FakeProbe(), FakeStore(), FakeBot()).status()
    out = TelegramStatusOut(**asdict(status)).model_dump_json()
    assert TOKEN not in out
    assert '"username":"railtech_test_bot"' in out


def test_token_input_is_masked_in_repr() -> None:
    body = TelegramTokenIn.model_validate({"token": TOKEN, "password": PASSWORD})
    assert TOKEN not in repr(body)
    assert PASSWORD not in repr(body)
    assert TOKEN not in body.model_dump_json()


async def test_send_test_requires_channel(audit_log: list[dict[str, Any]]) -> None:
    with pytest.raises(ConflictError) as caught:
        await make(FakeProbe(), FakeStore()).send_test()
    assert caught.value.details["reason"] == Reason.CHANNEL_NOT_CONFIGURED


async def test_reauth_locks_after_threshold(audit_log: list[dict[str, Any]]) -> None:
    """Аудит P0-4: перебор пароля через «Токен бота» упирается в тот же lockout, что вход."""
    service = make(FakeProbe(), FakeStore())
    for _ in range(9):
        with pytest.raises(ValidationFailedError):
            await service.save_token(ADMIN, TOKEN, "wrong-password-1")
    with pytest.raises(AccountLockedError):
        await service.save_token(ADMIN, TOKEN, "wrong-password-1")
    with pytest.raises(AccountLockedError):  # верный пароль блокировку не снимает
        await service.save_token(ADMIN, TOKEN, PASSWORD)


async def test_profile_saved_with_audit_actor_even_without_bot() -> None:
    saved: list[tuple[str, Any, Any]] = []

    class Settings(FakeSettings):
        async def update(self, key: str, value: Any, user_id: Any, actor: Any = None) -> None:
            saved.append((key, value, actor))

    async def no_bot() -> None:
        return None

    bot = FakeBot()
    service = svc.TelegramIntegrationService(
        fake_sessions(),
        Settings(),  # type: ignore[arg-type]
        FakeStore(),
        FakeProbe(),
        bot,
        no_bot,
        mode="polling",
    )
    body = BotProfileSettings.model_validate({"name": {"ru": "RailTech", "uz": "", "en": ""}})
    _, result = await service.save_profile(ADMIN, body)
    assert (saved[0][0], saved[0][2]) == ("bot_profile", ADMIN.actor)
    assert result is not None
    assert (result.ok, result.error) == (False, "bot_not_running")
    assert bot.profile is result  # итог публикации записан в БД — его увидит и crm-bot, и экран
