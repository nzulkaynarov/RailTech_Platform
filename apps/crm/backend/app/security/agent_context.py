"""Подписанный контекст вызова инструментов агента (SPEC §1.5, §7.1; ADR-0008).

Идентификаторы лида/клиента никогда не приходят от модели: оркестратор агента
подписывает контекст ключом из env и передаёт его MCP-серверу в заголовке
`X-Agent-Context`. Формат: `base64url(json).base64url(hmac_sha256)`.
Сервер проверяет подпись (constant-time) и срок жизни (по умолчанию 60 с).
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

HEADER_NAME: Final = "X-Agent-Context"
DEFAULT_TTL_S: Final = 60
CLOCK_SKEW_S: Final = 5

AgentMode = Literal["prospect", "customer"]


class AgentContextError(Exception):
    """Контекст отсутствует, повреждён, подделан или просрочен."""


class AgentContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lead_id: int = Field(gt=0)
    client_id: int | None = Field(default=None, gt=0)
    mode: AgentMode
    language: Literal["ru", "uz", "en"]
    trace_id: str | None = None
    iat: int
    exp: int


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: str, key: bytes) -> str:
    return _b64encode(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def issue(
    key: bytes,
    *,
    lead_id: int,
    mode: AgentMode,
    language: Literal["ru", "uz", "en"],
    client_id: int | None = None,
    trace_id: str | None = None,
    ttl_s: int = DEFAULT_TTL_S,
    now: Callable[[], float] = time.time,
) -> str:
    if mode == "customer" and client_id is None:
        raise ValueError("customer mode requires a verified client_id")
    issued = int(now())
    context = AgentContext(
        lead_id=lead_id,
        client_id=client_id,
        mode=mode,
        language=language,
        trace_id=trace_id,
        iat=issued,
        exp=issued + ttl_s,
    )
    payload = _b64encode(context.model_dump_json().encode("utf-8"))
    return f"{payload}.{_sign(payload, key)}"


def verify(token: str | None, key: bytes, *, now: Callable[[], float] = time.time) -> AgentContext:
    if not token:
        raise AgentContextError("missing agent context")
    payload, sep, signature = token.partition(".")
    if not sep or not payload or not signature:
        raise AgentContextError("malformed agent context")
    if not hmac.compare_digest(_sign(payload, key), signature):
        raise AgentContextError("invalid signature")
    try:
        context = AgentContext.model_validate(json.loads(_b64decode(payload)))
    except (ValueError, ValidationError) as exc:
        raise AgentContextError("malformed agent context") from exc
    current = now()
    if context.exp < current or context.iat > current + CLOCK_SKEW_S:
        raise AgentContextError("expired agent context")
    if context.mode == "customer" and context.client_id is None:
        raise AgentContextError("customer context without client_id")
    return context
