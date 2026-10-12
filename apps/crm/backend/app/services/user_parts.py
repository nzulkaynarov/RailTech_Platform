"""Проверки ввода пользователя (вынесены из `services/users.py`, ≤ 400 строк)."""

from collections.abc import Sequence

from app.domain.errors import Reason, ValidationFailedError
from app.models.auth import ROLES


def check_roles(roles: Sequence[str]) -> None:
    unknown = set(roles) - set(ROLES)
    if unknown or not roles:
        raise ValidationFailedError("unknown or empty roles", field="roles")


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or len(value) > 255:
        raise ValidationFailedError("invalid email", reason=Reason.INVALID_EMAIL, field="email")
    return value
