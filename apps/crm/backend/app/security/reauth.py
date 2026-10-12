"""Повторный ввод пароля (re-auth) с тем же счётчиком неудач, что и у входа (SPEC §11, ADR-0005).

Без счётчика re-auth — обход lockout: укравший сессию перебирает пароль через «Сменить пароль»
или «Токен бота». Здесь одно правило для входа и для re-auth: `failed_logins`/`locked_until`
пользователя, тот же порог и длительность блокировки (`Settings.login_*`).

Функции меняют счётчики объекта `User`; вызывающий коммитит транзакцию и только потом
бросает возвращённую ошибку (иначе счётчик откатится вместе с ошибкой).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from app.domain.errors import AccountLockedError, DomainError, Reason, ValidationFailedError
from app.models.auth import User
from app.security.passwords import verify_password

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LockoutPolicy:
    max_failures: int = 10
    lockout_minutes: int = 15


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


def locked_error(user: User) -> AccountLockedError:
    until = user.locked_until.isoformat() if user.locked_until is not None else None
    return AccountLockedError("account locked", until=until)


def register_failure(user: User, now: datetime, policy: LockoutPolicy) -> bool:
    """Учесть неудачу; True — порог достигнут и аккаунт заблокирован."""
    user.failed_logins += 1
    if user.failed_logins < policy.max_failures:
        return False
    user.locked_until = now + timedelta(minutes=policy.lockout_minutes)
    user.failed_logins = 0
    logger.warning("account_locked", user_id=user.id)
    return True


def check(
    user: User, password: str, now: datetime, policy: LockoutPolicy, *, field: str = "password"
) -> DomainError | None:
    """Проверить пароль для re-auth. `None` — верно (счётчик сброшен), иначе ошибка к броску.

    Заблокированный аккаунт — 423 до проверки пароля (верный пароль не снимает блокировку).
    """
    if is_locked(user, now):
        return locked_error(user)
    if verify_password(user.password_hash, password):
        user.failed_logins = 0
        return None
    if register_failure(user, now, policy):
        return locked_error(user)
    return ValidationFailedError("password is wrong", reason=Reason.WRONG_PASSWORD, field=field)
