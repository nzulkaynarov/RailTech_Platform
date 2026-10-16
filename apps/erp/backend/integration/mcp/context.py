"""Signed agent context verification for erp-mcp (CONTRACTS §5, packages/contracts/mcp-tools.json).

Формат заголовка X-Agent-Context: base64url(json).base64url(hmac_sha256).
Секрет: ERP_MCP_CONTEXT_KEY.
Срок жизни: 60 секунд.
Claims:
- crm_client_id: int
- erp_company_id: int | None (null в режиме prospect)
- mode: "prospect" | "customer"
- language: "ru" | "uz" | "en"
- exp: unix seconds (<= now + 60)
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import time
from typing import Any, Final, Optional

HEADER_NAME: Final = "X-Agent-Context"
DEFAULT_TTL_S: Final = 60
CLOCK_SKEW_S: Final = 5


class AgentContextError(Exception):
    """Контекст отсутствует, повреждён, подделан или просрочен."""


@dataclasses.dataclass(frozen=True)
class AgentContext:
    crm_client_id: int
    erp_company_id: Optional[int]
    mode: str  # "prospect" | "customer"
    language: str  # "ru" | "uz" | "en"
    exp: int
    iat: Optional[int] = None
    trace_id: Optional[str] = None


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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
) -> str:
    """Генерация подписанного токена X-Agent-Context."""
    if mode == "customer" and erp_company_id is None:
        raise ValueError("customer mode requires erp_company_id")

    current_time = int(time.time() if now is None else now)
    claims: dict[str, Any] = {
        "crm_client_id": crm_client_id,
        "erp_company_id": erp_company_id,
        "mode": mode,
        "language": language,
        "iat": current_time,
        "exp": current_time + ttl_s,
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

    crm_client_id = data.get("crm_client_id") or data.get("client_id")
    if crm_client_id is None or not isinstance(crm_client_id, int):
        raise AgentContextError("invalid or missing crm_client_id")

    mode = str(data.get("mode") or "").strip().lower()
    if mode not in ("prospect", "customer"):
        raise AgentContextError(f"invalid mode: {mode}")

    language = str(data.get("language") or "ru").strip().lower()
    if language not in ("ru", "uz", "en"):
        language = "ru"

    erp_company_id = data.get("erp_company_id")
    if erp_company_id is not None and not isinstance(erp_company_id, int):
        raise AgentContextError("invalid erp_company_id")

    if mode == "customer" and not erp_company_id:
        raise AgentContextError("customer mode requires erp_company_id")

    exp = data.get("exp")
    if exp is None or not isinstance(exp, (int, float)):
        raise AgentContextError("missing or invalid exp")

    current_time = time.time() if now is None else now
    if exp < current_time:
        raise AgentContextError("expired agent context")

    iat = data.get("iat")
    if iat is not None and isinstance(iat, (int, float)):
        if iat > current_time + CLOCK_SKEW_S:
            raise AgentContextError("context issued in future")
        iat = int(iat)

    return AgentContext(
        crm_client_id=crm_client_id,
        erp_company_id=erp_company_id,
        mode=mode,
        language=language,
        exp=int(exp),
        iat=iat,
        trace_id=data.get("trace_id"),
    )
