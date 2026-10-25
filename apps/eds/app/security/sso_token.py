"""Проверка SSO-токена сотрудника CRM для EDS (docs/architecture/sso-token.md, «Токен сотрудника для EDS»).

Порядок проверок — нормативный; отказ любой — `SsoTokenError` с `reason`, API превращает его в
401 `INVALID_SSO_TOKEN`:

1. подпись HS256 одним из действующих секретов `PLATFORM_SSO_SECRET` (ротация — два значения) — `signature`;
2. `iss` равен `crm` — `issuer`; `aud` равен `eds` — `audience`;
3. `exp` не прошёл (допуск часов 5 с) — `expired`; `exp − iat` не больше 60 с (с тем же допуском), `iat` не в будущем
   дальше допуска — `lifetime`;
4. `jti` одноразовый — проверяет и фиксирует `app.services.sso` (`replayed`).

Структурно неверный токен (не JWT, нет `exp`/`iat`/`jti`/`sub`, `sub` не число) — `malformed`. Права и роль из токена
не берутся: пользователь ищется только по `sub` в проекции сотрудников.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import jwt

AUDIENCE = "eds"
ISSUER = "crm"  # SSO-токен для EDS выдаёт только CRM (sso-token.md, «Токен сотрудника для EDS»)
ALGORITHM = "HS256"
MAX_LIFETIME_S = 60
LEEWAY_S = 5
JTI_MAX_LENGTH = 128


class SsoTokenError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SsoClaims:
    iss: str | None
    sub: int
    jti: str
    iat: float
    exp: float


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SsoTokenError("malformed")
    return float(value)


def verify_sso_token(token: str, secrets: Sequence[str], *, now: float) -> SsoClaims:
    payload = _decode(token, secrets)
    if payload.get("iss") != ISSUER:
        raise SsoTokenError("issuer")
    audience = payload.get("aud")
    if not isinstance(audience, str) or audience != AUDIENCE:
        raise SsoTokenError("audience")
    exp = _number(payload.get("exp"))
    iat = _number(payload.get("iat"))
    if now > exp + LEEWAY_S:
        raise SsoTokenError("expired")
    if exp < iat or exp - iat > MAX_LIFETIME_S + LEEWAY_S or iat > now + LEEWAY_S:
        raise SsoTokenError("lifetime")
    jti = payload.get("jti")
    if not isinstance(jti, str) or not 0 < len(jti) <= JTI_MAX_LENGTH:
        raise SsoTokenError("malformed")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.isascii() or not sub.isdigit() or len(sub) > 18:
        raise SsoTokenError("malformed")
    issuer = payload.get("iss")
    return SsoClaims(iss=issuer if isinstance(issuer, str) else None, sub=int(sub), jti=jti, iat=iat, exp=exp)


def _decode(token: str, secrets: Sequence[str]) -> dict[str, Any]:
    """Подпись и структура токена; срок, `aud` и прочее проверяются выше, в нашем порядке."""
    options: Any = {
        "verify_signature": True,
        "verify_exp": False,
        "verify_iat": False,
        "verify_nbf": False,
        "verify_aud": False,
        "verify_iss": False,
    }
    signature_failed = False
    for secret in secrets:
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM], options=options)
        except (jwt.InvalidSignatureError, jwt.InvalidAlgorithmError):
            signature_failed = True
            continue
        except jwt.InvalidTokenError as exc:
            raise SsoTokenError("malformed") from exc
        if not isinstance(payload, dict):
            raise SsoTokenError("malformed")
        return payload
    raise SsoTokenError("signature" if signature_failed else "malformed")
