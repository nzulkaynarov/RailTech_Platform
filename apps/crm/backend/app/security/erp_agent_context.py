"""Подписанный контекст вызова `erp-mcp` (CONTRACTS §5, `mcp-tools.json`; M3-CRM-07).

Формат другой, чем у `kb`/`crm`/`docs` (`agent_context.py`): claims ERP — `crm_client_id`,
`erp_company_id`, `mode`, `language`, `iat`, `exp`, `jti`, `trace_id`; ключ — `ERP_MCP_CONTEXT_KEY`
(общий с ERP), а не ключ CRM. Выпускает только код (SPEC §1.5): идентификаторы клиента и компании
берутся из БД по проверенной привязке Telegram, модель их не видит и не передаёт. Новый `jti` на
КАЖДЫЙ выпуск — ERP принимает его один раз.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

HEADER_NAME: Final = "X-Agent-Context"
TTL_S: Final = 60

Language = Literal["ru", "uz", "en"]


@dataclass(frozen=True, slots=True)
class ErpScope:
    """Чьими данными можно пользоваться ходу: клиент CRM и его компания в ERP (режим customer)."""

    crm_client_id: int
    erp_company_id: int
    language: Language = "ru"
    trace_id: str | None = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_erp_context(
    key: bytes,
    scope: ErpScope,
    *,
    now: Callable[[], float] = time.time,
    new_jti: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> str:
    """`base64url(json).base64url(HMAC-SHA256)`; режим всегда `customer` (лидам erp-mcp закрыт)."""
    if not key:
        raise ValueError("ERP_MCP_CONTEXT_KEY is not configured")
    if scope.crm_client_id <= 0 or scope.erp_company_id <= 0:
        raise ValueError("customer scope requires positive crm_client_id and erp_company_id")
    issued = int(now())
    claims: dict[str, object] = {
        "crm_client_id": scope.crm_client_id,
        "erp_company_id": scope.erp_company_id,
        "mode": "customer",
        "language": scope.language,
        "iat": issued,
        "exp": issued + TTL_S,
        "jti": new_jti(),
    }
    if scope.trace_id:
        claims["trace_id"] = scope.trace_id
    payload = _b64(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"
