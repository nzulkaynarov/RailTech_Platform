"""Клиент сопряжения с ERP (M3-CRM-10, CONTRACTS §2): `/pairing/accept` и `/pairing/rotate`.

Отдельный модуль, а не часть `integrations/erp.py`: у сопряжения своя аутентификация (код
сопряжения, а для ротации — действующий токен, переданный явно) и свои ошибки. Тела запросов и
коды в логи не попадают; в ответах ERP читаем только нужные поля (читатель терпимый,
CONTRACTS §3): новые поля ответа не ломают CRM.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from app.domain.erp_connector import PAIRING_ACCEPT_PATH, PAIRING_ROTATE_PATH, base_url_problem
from app.domain.errors import (
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.security import pairing_proof

logger = structlog.get_logger(__name__)

PAIRING_TIMEOUT_S = 10.0
_SECRET_BYTES = 48  # token_urlsafe(48) = 64 символа [A-Za-z0-9_-], контракт `PairingSecret`: 32…512

_PROOF_DETAILS = frozenset(
    {"PAIRING_PROOF_INVALID", "PAIRING_PROOF_EXPIRED", "PAIRING_PROOF_REPLAYED"}
)
_CODE_REASONS = {
    "PAIRING_CODE_INVALID": Reason.ERP_PAIRING_CODE_INVALID,
    "PAIRING_CODE_EXPIRED": Reason.ERP_PAIRING_CODE_EXPIRED,
    "PAIRING_CODE_USED": Reason.ERP_PAIRING_CODE_USED,
}


@dataclass(frozen=True, slots=True, repr=False)
class PairingSecrets:
    """Три секрета, которые CRM генерирует сама; `repr` скрыт, чтобы они не попали в лог."""

    crm_to_erp_token: str
    erp_to_crm_token: str
    webhook_secret: str

    def __repr__(self) -> str:
        return "PairingSecrets(<hidden>)"

    @classmethod
    def generate(cls) -> "PairingSecrets":
        return cls(
            crm_to_erp_token=secrets.token_urlsafe(_SECRET_BYTES),
            erp_to_crm_token=secrets.token_urlsafe(_SECRET_BYTES),
            webhook_secret=secrets.token_urlsafe(_SECRET_BYTES),
        )

    def body_bytes(self) -> bytes:
        """Тело запроса — ровно эти байты уходят в ERP и покрываются хешем доказательства."""
        return json.dumps(self.body(), separators=(",", ":")).encode()

    def body(self) -> dict[str, str]:
        return {
            "crm_to_erp_token": self.crm_to_erp_token,
            "erp_to_crm_token": self.erp_to_crm_token,
            "webhook_secret": self.webhook_secret,
        }


@dataclass(frozen=True, slots=True)
class PairingAccepted:
    paired_at: datetime
    erp_version: str


@dataclass(frozen=True, slots=True)
class PairingRotated:
    rotated_at: datetime
    previous_token_valid_until: datetime


class _AcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paired_at: datetime
    erp_version: str


class _RotatedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rotated_at: datetime
    previous_token_valid_until: datetime


class AmbiguousOutcomeError(UpstreamUnavailableError):
    """Запрос мог дойти до ERP и примениться, но ответа нет или он непонятен.

    Это ReadTimeout, 5xx, обрыв после отправки. Однозначный отказ (ConnectError, 4xx) — обычная
    `UpstreamUnavailableError`: ERP точно ничего не применила. После неоднозначного исхода CRM
    ничего не откатывает (см. `ErpPairingService.rotate`).
    """


class ErpPairingClient(Protocol):
    async def accept(
        self, base_url: str, code: str, secrets_: PairingSecrets
    ) -> PairingAccepted: ...

    async def accept_bootstrap(
        self, base_url: str, platform_secret: str, secrets_: PairingSecrets
    ) -> PairingAccepted: ...

    async def rotate(
        self, base_url: str, token: str, secrets_: PairingSecrets
    ) -> PairingRotated: ...


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", ""))
    except (ValueError, AttributeError):
        return ""


class HttpxErpPairingClient:
    """`POST {base_url}/api/integration/v1/pairing/(accept|rotate)`, таймаут 10 с."""

    def __init__(self, timeout_s: float = PAIRING_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    async def accept_bootstrap(
        self, base_url: str, platform_secret: str, secrets_: PairingSecrets
    ) -> PairingAccepted:
        """Первое сопряжение без кода: вместо кода — доказательство владения секретом платформы."""
        body = secrets_.body_bytes()
        proof = pairing_proof.sign(platform_secret, body)
        response = await self._send(
            base_url, PAIRING_ACCEPT_PATH, {pairing_proof.HEADER: proof}, body
        )
        if response.status_code == 401 and _detail(response) in _PROOF_DETAILS:
            raise ValidationFailedError(
                f"erp bootstrap: {_detail(response)}",
                reason=Reason.ERP_BOOTSTRAP_REJECTED,
                field="code",
            )
        if response.status_code == 409 and _detail(response) == "BOOTSTRAP_CLOSED":
            raise ValidationFailedError(
                "erp bootstrap: window is closed", reason=Reason.ERP_BOOTSTRAP_CLOSED, field="code"
            )
        return self._parse_accepted(response)

    async def accept(self, base_url: str, code: str, secrets_: PairingSecrets) -> PairingAccepted:
        response = await self._post(base_url, PAIRING_ACCEPT_PATH, code, secrets_)
        if response.status_code == 401:
            detail = _detail(response)
            reason = _CODE_REASONS.get(detail, Reason.ERP_PAIRING_CODE_INVALID)
            raise ValidationFailedError(
                f"erp pairing: {detail or 'code rejected'}", reason=reason, field="code"
            )
        return self._parse_accepted(response)

    def _parse_accepted(self, response: httpx.Response) -> PairingAccepted:
        self._ensure_ok(response)
        try:
            payload = _AcceptedPayload.model_validate_json(response.content)
        except ValidationError as exc:
            raise AmbiguousOutcomeError(
                f"erp pairing: bad response schema ({exc.error_count()} errors)",
                reason=Reason.ERP_BAD_RESPONSE,
            ) from exc
        return PairingAccepted(payload.paired_at, payload.erp_version)

    async def rotate(self, base_url: str, token: str, secrets_: PairingSecrets) -> PairingRotated:
        response = await self._post(base_url, PAIRING_ROTATE_PATH, token, secrets_)
        if response.status_code == 401:
            raise UpstreamUnavailableError("erp rotate: HTTP 401", reason=Reason.ERP_UNAUTHORIZED)
        self._ensure_ok(response)
        try:
            payload = _RotatedPayload.model_validate_json(response.content)
        except ValidationError as exc:
            raise AmbiguousOutcomeError(
                f"erp rotate: bad response schema ({exc.error_count()} errors)",
                reason=Reason.ERP_BAD_RESPONSE,
            ) from exc
        return PairingRotated(payload.rotated_at, payload.previous_token_valid_until)

    async def _post(
        self, base_url: str, path: str, bearer: str, secrets_: PairingSecrets
    ) -> httpx.Response:
        return await self._send(
            base_url, path, {"Authorization": f"Bearer {bearer}"}, secrets_.body_bytes()
        )

    async def _send(
        self, base_url: str, path: str, auth_headers: dict[str, str], content: bytes
    ) -> httpx.Response:
        problem = base_url_problem(base_url)
        if problem is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        headers = {
            **auth_headers,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                return await client.post(
                    base_url.rstrip("/") + path, content=content, headers=headers
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Соединения не было: запрос до ERP не дошёл — исход однозначный.
            raise UpstreamUnavailableError(
                type(exc).__name__, reason=Reason.ERP_UNAVAILABLE
            ) from exc
        except httpx.InvalidURL as exc:
            raise ValidationFailedError(
                "erp base url is invalid", reason=Reason.ERP_INVALID_URL, field="base_url"
            ) from exc
        except httpx.HTTPError as exc:
            # ReadTimeout, обрыв после отправки: ERP могла принять запрос.
            raise AmbiguousOutcomeError(type(exc).__name__, reason=Reason.ERP_UNAVAILABLE) from exc

    @staticmethod
    def _ensure_ok(response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in (404, 405):
            raise UpstreamUnavailableError(
                f"erp pairing: HTTP {status}", reason=Reason.ERP_PAIRING_UNSUPPORTED
            )
        if status == 429:
            retry = response.headers.get("Retry-After", "")
            raise UpstreamUnavailableError(
                f"erp pairing: rate limited, retry after {retry or '?'} s",
                reason=Reason.ERP_UNAVAILABLE,
            )
        if status == 422:
            raise UpstreamUnavailableError(
                "erp pairing: ERP rejected the secrets (422)", reason=Reason.ERP_BAD_RESPONSE
            )
        if status >= 500 or status < 400:
            raise AmbiguousOutcomeError(
                f"erp pairing: HTTP {status}", reason=Reason.ERP_BAD_RESPONSE
            )
        raise UpstreamUnavailableError(
            f"erp pairing: HTTP {status}", reason=Reason.ERP_BAD_RESPONSE
        )
