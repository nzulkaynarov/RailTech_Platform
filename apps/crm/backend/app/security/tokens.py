"""Access JWT (HS256, 15 мин) и непрозрачные refresh-токены (хранится только sha256)."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt

ALGORITHM: Final = "HS256"
ISSUER: Final = "railtech-crm"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class TokenError(Exception):
    """Токен невалиден, просрочен или подписан не тем ключом."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: int
    roles: tuple[str, ...]
    must_change_password: bool
    # Версия пароля на момент выпуска: `password_changed_at` в микросекундах epoch (0 — не менялся).
    # Токен с устаревшей версией выпущен до смены пароля и не принимается.
    password_version: int = 0


def issue_access(key: bytes, claims: AccessClaims, ttl_s: int, now: datetime | None = None) -> str:
    if len(key) < 32:
        raise TokenError("JWT key must be at least 32 bytes")
    issued = now or datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "sub": str(claims.user_id),
        "roles": list(claims.roles),
        "mcp": claims.must_change_password,
        "pwv": claims.password_version,
        "iat": issued,
        "exp": issued + timedelta(seconds=ttl_s),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def decode_access(key: bytes, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(type(exc).__name__) from exc
    if payload.get("typ") != "access":
        raise TokenError("wrong token type")
    return AccessClaims(
        user_id=int(payload["sub"]),
        roles=tuple(str(r) for r in payload.get("roles", [])),
        must_change_password=bool(payload.get("mcp", False)),
        password_version=int(payload.get("pwv", 0)),
    )


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_family() -> str:
    return uuid.uuid4().hex


def password_version(changed_at: datetime | None) -> int:
    """Версия пароля для токена: момент смены в микросекундах (точно, без плавающей точки)."""
    if changed_at is None:
        return 0
    return (changed_at - _EPOCH) // timedelta(microseconds=1)


def closed_by_password_change(created_at: datetime, changed_at: datetime | None) -> bool:
    """Refresh-токен создан раньше смены пароля: точное сравнение, оба времени — часы приложения."""
    return changed_at is not None and created_at < changed_at
