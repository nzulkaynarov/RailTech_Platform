"""Второй фактор входа (ДВ-4; реестр рисков Д1): код приложения-аутентификатора (TOTP, RFC 6238).

Готовая библиотека `pyotp`: шаг 30 с, 6 цифр, допуск ±1 шаг на расхождение часов; принятый шаг
запоминается (`totp_last_step`) — тот же код второй раз не проходит. Резервные коды — 8 штук
`XXXX-XXXX` без путаемых символов, в базе sha256, каждый на один вход.

Токены — JWT тем же ключом, что access, со своим `typ`:
* `2fa_challenge` — 5 минут между паролем и кодом (`sub`, версия пароля);
* `2fa_enroll` — 15 минут на настройку фактора сразу после пароля, когда он обязателен (ДВ-4б);
* `step_up` — 5 минут «свежего кода» перед чувствительным действием (ДВ-4б), заголовок
  `X-Step-Up-Token`; привязан к сотруднику, версии пароля и версии фактора;
* `2fa_device` — «запомнить устройство» на 30 дней (`sub`, версия пароля и версия второго
  фактора — момент включения: после выключения и повторного включения прежние метки не действуют).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt
import pyotp

from app.security.tokens import ALGORITHM, ISSUER, TokenError

CHALLENGE_TTL: Final = timedelta(minutes=5)
DEVICE_TTL: Final = timedelta(days=30)
ENROLL_TTL: Final = timedelta(minutes=15)
STEP_UP_TTL: Final = timedelta(minutes=5)
BACKUP_CODES: Final = 8
_BACKUP_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без 0/O, 1/I
_STEP_S: Final = 30


def new_secret() -> str:
    return pyotp.random_base32()


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    """Адрес для QR-кода приложения: `otpauth://totp/<issuer>:<account>?secret=…&issuer=…`."""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer or "Platform")


def accept_code(secret: str, code: str, last_step: int | None, now: datetime) -> int | None:
    """Шаг 30 с, на котором код верен (±1), или None; шаг не позже `last_step` не принимается."""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != 6:
        return None
    totp = pyotp.TOTP(secret)
    current = int(now.timestamp()) // _STEP_S
    for step in (current, current - 1, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if secrets.compare_digest(totp.at(step * _STEP_S), digits):
            return step
    return None


def _backup_hash(code: str) -> str:
    normalized = "".join(ch for ch in code.upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def new_backup_codes() -> tuple[list[str], list[str]]:
    """(коды для человека, их хеши для базы)."""
    codes = []
    for _ in range(BACKUP_CODES):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes, [_backup_hash(code) for code in codes]


def consume_backup_code(hashes: list[str], code: str) -> list[str] | None:
    """Хеши без использованного кода или None, если такого кода нет."""
    digest = _backup_hash(code)
    if not any(secrets.compare_digest(digest, known) for known in hashes):
        return None
    return [known for known in hashes if known != digest]


def version_of(enabled_at: datetime | None) -> int:
    return int(enabled_at.timestamp() * 1_000_000) if enabled_at else 0


@dataclass(frozen=True, slots=True)
class FactorClaims:
    user_id: int
    password_version: int
    factor_version: int = 0


def _issue(key: bytes, typ: str, claims: FactorClaims, ttl: timedelta, now: datetime) -> str:
    payload = {
        "iss": ISSUER,
        "sub": str(claims.user_id),
        "pwv": claims.password_version,
        "fv": claims.factor_version,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
        "typ": typ,
    }
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def _decode(key: bytes, typ: str, token: str) -> FactorClaims:
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
    if payload.get("typ") != typ:
        raise TokenError("wrong token type")
    return FactorClaims(int(payload["sub"]), int(payload.get("pwv", 0)), int(payload.get("fv", 0)))


def issue_challenge(key: bytes, claims: FactorClaims, now: datetime | None = None) -> str:
    return _issue(key, "2fa_challenge", claims, CHALLENGE_TTL, now or datetime.now(UTC))


def decode_challenge(key: bytes, token: str) -> FactorClaims:
    return _decode(key, "2fa_challenge", token)


def issue_device(key: bytes, claims: FactorClaims, now: datetime | None = None) -> str:
    return _issue(key, "2fa_device", claims, DEVICE_TTL, now or datetime.now(UTC))


def decode_device(key: bytes, token: str) -> FactorClaims:
    return _decode(key, "2fa_device", token)


def issue_enroll(key: bytes, claims: FactorClaims, now: datetime | None = None) -> str:
    return _issue(key, "2fa_enroll", claims, ENROLL_TTL, now or datetime.now(UTC))


def decode_enroll(key: bytes, token: str) -> FactorClaims:
    return _decode(key, "2fa_enroll", token)


def issue_step_up(key: bytes, claims: FactorClaims, now: datetime | None = None) -> str:
    return _issue(key, "step_up", claims, STEP_UP_TTL, now or datetime.now(UTC))


def decode_step_up(key: bytes, token: str) -> FactorClaims:
    return _decode(key, "step_up", token)
