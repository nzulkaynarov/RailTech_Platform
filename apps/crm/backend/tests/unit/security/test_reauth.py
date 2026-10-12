"""Re-auth с lockout входа (аудит 2026-10-12, P0-4)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.errors import AccountLockedError, ValidationFailedError
from app.security import reauth
from app.security.passwords import hash_password

PASSWORD = "correct-horse-battery-1"
NOW = datetime(2026, 10, 12, 10, tzinfo=UTC)
POLICY = reauth.LockoutPolicy(max_failures=3, lockout_minutes=15)
HASH = hash_password(PASSWORD)


def user(failed: int = 0, locked_until: datetime | None = None) -> Any:
    return SimpleNamespace(
        id=1, password_hash=HASH, failed_logins=failed, locked_until=locked_until
    )


@pytest.mark.parametrize(
    ("failed", "locked", "password", "error", "failed_after", "locks"),
    [
        (0, None, PASSWORD, None, 0, False),
        (2, None, PASSWORD, None, 0, False),  # верный пароль сбрасывает счётчик
        (0, None, "nope", ValidationFailedError, 1, False),
        (1, None, "nope", ValidationFailedError, 2, False),
        (2, None, "nope", AccountLockedError, 0, True),  # порог — блокировка
        (0, NOW + timedelta(minutes=5), PASSWORD, AccountLockedError, 0, False),
        (0, NOW - timedelta(minutes=1), PASSWORD, None, 0, False),  # блокировка истекла
    ],
)
def test_check(
    failed: int,
    locked: datetime | None,
    password: str,
    error: type[Exception] | None,
    failed_after: int,
    locks: bool,
) -> None:
    u = user(failed, locked)
    result = reauth.check(u, password, NOW, POLICY)
    assert (type(result) if result is not None else None) is error
    assert u.failed_logins == failed_after
    if locks:
        assert u.locked_until == NOW + timedelta(minutes=15)
