"""«Подключения»: пароль обязателен, неверный токен не сохраняется, токен не уходит в аудит/логи."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

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
    TokenSource,
)
from app.schemas.integrations import TelegramStatusOut, TelegramTokenIn
from app.security.passwords import hash_password
from app.security.principal import Principal
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services import integrations as svc

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
    mode = "polling"
    running = True
    source: TokenSource = "db"
    username = "railtech_test_bot"
    last_error = None

    def __init__(self) -> None:
        self.restarts = 0

    async def restart(self) -> None:
        self.restarts += 1


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
        bot,
        no_bot,
        mode="polling",
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
    assert bot.restarts == 1
    assert len(audit_log) == 1
    assert TOKEN not in repr(audit_log)
    assert audit_log[0]["after"]["last4"] == "AbCd"
    assert TOKEN not in repr(logs)
    assert PASSWORD not in repr(logs)


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
