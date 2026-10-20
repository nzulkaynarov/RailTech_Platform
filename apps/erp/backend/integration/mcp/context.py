"""Signed agent context verification for erp-mcp (CONTRACTS §5, packages/contracts/mcp-tools.json).

Формат заголовка X-Agent-Context: base64url(json).base64url(hmac_sha256).
Секрет: ERP_MCP_CONTEXT_KEY.
Срок жизни: 60 секунд (FIX-12: строгие типы, обязательные iat/exp/jti).
Claims (типы строгие: `bool` не принимается как int, строки не приводятся):
- crm_client_id: int
- erp_company_id: int | None (в режиме prospect — строго null, в customer — обязателен; FIX-36)
- mode: "prospect" | "customer"
- language: "ru" | "uz" | "en"
- iat: int, unix seconds (не из будущего, допуск 5 с)
- exp: int, unix seconds; exp − iat <= 60 и exp <= now + 60 (допуск 5 с)
- jti: UUID v4 строкой; одноразовый, помнится 10 минут (`mark_used`)
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Final, Optional

from django.core.cache import cache

HEADER_NAME: Final = "X-Agent-Context"
DEFAULT_TTL_S: Final = 60
CLOCK_SKEW_S: Final = 5
JTI_CACHE_TTL_S: Final = 600
MODES: Final = ("prospect", "customer")
LANGUAGES: Final = ("ru", "uz", "en")


class AgentContextError(Exception):
    """Контекст отсутствует, повреждён, подделан или просрочен."""


@dataclasses.dataclass(frozen=True)
class AgentContext:
    crm_client_id: int
    erp_company_id: Optional[int]
    mode: str  # "prospect" | "customer"
    language: str  # "ru" | "uz" | "en"
    iat: int
    exp: int
    jti: str
    trace_id: Optional[str] = None


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _is_int(value: Any) -> bool:
    """Строго JSON-integer: `True` — это bool, а не компания 1."""
    return type(value) is int


def _is_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def _sign(payload: str, key: bytes) -> str:
    return _b64encode(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def _to_bytes(key: str | bytes) -> bytes:
    return key.encode("utf-8") if isinstance(key, str) else key


def issue_agent_context(
    key: str | bytes,
    *,
    crm_client_id: int,
    mode: str,
    language: str = "ru",
    erp_company_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    ttl_s: int = DEFAULT_TTL_S,
    now: Optional[float] = None,
    jti: Optional[str] = None,
) -> str:
    """Генерация подписанного токена X-Agent-Context."""
    if mode == "customer" and erp_company_id is None:
        raise ValueError("customer mode requires erp_company_id")
    if mode == "prospect" and erp_company_id is not None:
        raise ValueError("prospect mode requires erp_company_id to be null")

    current_time = int(time.time() if now is None else now)
    claims: dict[str, Any] = {
        "crm_client_id": crm_client_id,
        "erp_company_id": erp_company_id,
        "mode": mode,
        "language": language,
        "iat": current_time,
        "exp": current_time + ttl_s,
        "jti": jti or str(uuid.uuid4()),
    }
    if trace_id is not None:
        claims["trace_id"] = trace_id

    payload = _b64encode(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    key_bytes = _to_bytes(key)
    sig = _sign(payload, key_bytes)
    return f"{payload}.{sig}"


def verify_agent_context(
    token: Optional[str],
    key: str | bytes,
    *,
    now: Optional[float] = None,
) -> AgentContext:
    """Проверка и декодирование токена X-Agent-Context."""
    if not token or not str(token).strip():
        raise AgentContextError("missing agent context")

    token_str = str(token).strip()
    payload, sep, signature = token_str.partition(".")
    if not sep or not payload or not signature:
        raise AgentContextError("malformed agent context")

    key_bytes = _to_bytes(key)
    expected_sig = _sign(payload, key_bytes)
    if not hmac.compare_digest(expected_sig, signature):
        raise AgentContextError("invalid signature")

    try:
        raw_json = _b64decode(payload)
        data = json.loads(raw_json.decode("utf-8"))
    except Exception as exc:
        raise AgentContextError("malformed agent context payload") from exc

    if not isinstance(data, dict):
        raise AgentContextError("context payload must be a JSON object")

    crm_client_id = data.get("crm_client_id")
    if not _is_int(crm_client_id):
        raise AgentContextError("invalid or missing crm_client_id")

    mode = data.get("mode")
    if mode not in MODES:
        raise AgentContextError("invalid mode")

    language = data.get("language")
    if language not in LANGUAGES:
        raise AgentContextError("invalid language")

    erp_company_id = data.get("erp_company_id")
    if erp_company_id is not None and not _is_int(erp_company_id):
        raise AgentContextError("invalid erp_company_id")

    if mode == "customer" and not erp_company_id:
        raise AgentContextError("customer mode requires erp_company_id")
    if mode == "prospect" and erp_company_id is not None:
        # Лид ещё не клиент: контекст с компанией в режиме prospect — подделка или ошибка выпускающей стороны.
        raise AgentContextError("prospect mode requires erp_company_id to be null")

    iat = data.get("iat")
    if not _is_int(iat):
        raise AgentContextError("missing or invalid iat")
    exp = data.get("exp")
    if not _is_int(exp):
        raise AgentContextError("missing or invalid exp")

    jti = data.get("jti")
    if not _is_uuid4(jti):
        raise AgentContextError("missing or invalid jti")

    trace_id = data.get("trace_id")
    if trace_id is not None and not isinstance(trace_id, str):
        raise AgentContextError("invalid trace_id")

    current_time = time.time() if now is None else now
    if exp < current_time:
        raise AgentContextError("expired agent context")
    if exp <= iat or exp - iat > DEFAULT_TTL_S:
        raise AgentContextError("invalid agent context lifetime")
    if exp > current_time + DEFAULT_TTL_S + CLOCK_SKEW_S:
        raise AgentContextError("agent context expires too far in the future")
    if iat > current_time + CLOCK_SKEW_S:
        raise AgentContextError("context issued in future")

    return AgentContext(
        crm_client_id=crm_client_id,
        erp_company_id=erp_company_id,
        mode=mode,
        language=language,
        iat=iat,
        exp=exp,
        jti=jti.lower(),
        trace_id=trace_id,
    )


def mark_used(context: AgentContext) -> None:
    """Одноразовость: `jti` принимается один раз, помнится 10 минут. Повтор — AgentContextError."""
    if not cache.add(f"erp_mcp_jti:{context.jti}", True, timeout=JTI_CACHE_TTL_S):
        raise AgentContextError("agent context replay")
