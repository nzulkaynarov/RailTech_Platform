"""Пароли: argon2id (SPEC §11), временные пароли для создания/сброса админом."""

import secrets
import string
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH: Final = 10
_HASHER: Final = PasswordHasher()
_ALPHABET: Final = string.ascii_letters + string.digits


class WeakPasswordError(ValueError):
    """Пароль не проходит минимальные требования."""


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


def temporary_password(length: int = 14) -> str:
    """Временный пароль: показывается админу один раз, при входе — обязательная смена."""
    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate


def validate_new_password(password: str, *, email: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_LENGTH} characters")
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        raise WeakPasswordError("password must contain letters and digits")
    if email and email.split("@")[0].lower() in password.lower():
        raise WeakPasswordError("password must not contain the email name")
