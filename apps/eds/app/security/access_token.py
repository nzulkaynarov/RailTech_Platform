"""Токен доступа EDS: выдаётся обменом SSO-токена, проверяется на каждом запросе.

JWT HS256, секрет `EDS_ACCESS_SECRET`, `iss = eds`, `aud = eds-api`, `sub` = `crm_user_id`, срок 15 минут, без refresh
(истёк — BFF берёт у CRM новый токен сотрудника и обменивает снова). Права в токен не кладутся: их берут из проекции
сотрудников на момент запроса, поэтому отзыв роли действует сразу.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ISSUER = "eds"
AUDIENCE = "eds-api"
ALGORITHM = "HS256"
TTL_SECONDS = 900


class AccessTokenError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AccessClaims:
    crm_user_id: int
    jti: str
    exp: int


def issue_access_token(crm_user_id: int, secret: str, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(crm_user_id),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=TTL_SECONDS)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_access_token(token: str, secret: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AccessTokenError("expired") from exc
    except (jwt.InvalidSignatureError, jwt.InvalidAlgorithmError) as exc:
        raise AccessTokenError("signature") from exc
    except jwt.InvalidTokenError as exc:
        raise AccessTokenError("malformed") from exc
    sub = payload["sub"]
    if not isinstance(sub, str) or not sub.isascii() or not sub.isdigit():
        raise AccessTokenError("malformed")
    return AccessClaims(crm_user_id=int(sub), jti=str(payload["jti"]), exp=int(payload["exp"]))
