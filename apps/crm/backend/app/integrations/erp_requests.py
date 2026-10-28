"""«Создать заявку» в ERP: `POST /api/integration/v1/clients/{crm_client_id}/requests` (шов 0.9.0,
CRM-03, W16-D1-2).

Клиент уже передан (`/clients/handoff`); ERP создаёт сделку процесса v3 с номером ЗВ и менеджером
заявки и публикует `request.created`. Идемпотентно по `crm_request_id` (строка `deals` CRM); ключ
`Idempotency-Key` — детерминированный от неё же, повтор задачи не задваивает заявку. Ошибки — как у
передачи: 404 `CLIENT_NOT_FOUND` и 422 — постоянные, 401/5xx/таймаут — временные, 429 — пауза
`Retry-After`.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.domain.erp_connector import base_url_problem
from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import HandoffContactPayload, rate_limited, resolve_connection
from app.integrations.erp_transport import SharedAsyncClient, send
from app.security.secrets_store import SecretsStore
from app.services.settings import SettingsService

_NAMESPACE = uuid.UUID("6f1d8a52-3c1e-4c55-9d7e-2b0e1a6c7d31")


def request_idempotency_key(deal_id: int) -> str:
    """Один ключ на заявку CRM для всех попыток: ERP хранит ключ 7 дней, отвечает первым ответом."""
    return str(uuid.uuid5(_NAMESPACE, f"crm-request:{deal_id}"))


@dataclass(frozen=True, slots=True)
class ClientRequestPayload:
    crm_client_id: int
    crm_request_id: int
    summary: str
    owner_crm_user_id: int
    owner_name: str
    urgency: str = "normal"
    crm_lead_id: int | None = None
    contact: HandoffContactPayload | None = None
    product_interest: tuple[str, ...] = ()
    letter_file_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ClientRequestResult:
    erp_company_id: int
    erp_request_id: int
    number: str


def payload_to_dict(p: ClientRequestPayload) -> dict[str, Any]:
    contact = p.contact
    return {
        "crm_request_id": p.crm_request_id,
        "crm_lead_id": p.crm_lead_id,
        "contact": None
        if contact is None
        else {
            "crm_contact_id": contact.crm_contact_id,
            "name": contact.name,
            "phone": contact.phone or "",
            "email": contact.email or "",
            "telegram_user_id": contact.telegram_user_id,
            "language": contact.language,
            "is_primary": contact.is_primary,
            "preferred_channel": contact.preferred_channel,
        },
        "need": {"summary": p.summary, "product_interest": list(p.product_interest)},
        "owner": {"crm_user_id": p.owner_crm_user_id, "name": p.owner_name},
        "urgency": p.urgency,
        "letter_file_id": str(p.letter_file_id) if p.letter_file_id else None,
        "process": "v3",
    }


class ErpRequestClient(Protocol):
    async def create_client_request(self, payload: ClientRequestPayload) -> ClientRequestResult: ...


class HttpxErpRequestClient:
    def __init__(
        self,
        store: SecretsStore,
        config: Settings,
        settings: SettingsService | None = None,
        *,
        timeout_s: float = 10.0,
        http: SharedAsyncClient | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._settings = settings
        self._timeout_s = timeout_s
        self._http = http or SharedAsyncClient()

    async def create_client_request(self, payload: ClientRequestPayload) -> ClientRequestResult:
        connection = await resolve_connection(self._store, self._config, self._settings)
        if connection is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        problem = base_url_problem(connection.base_url)
        if problem is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        base = connection.base_url.rstrip("/")
        url = f"{base}/api/integration/v1/clients/{payload.crm_client_id}/requests"
        headers = {
            "Authorization": f"Bearer {connection.token}",
            "Idempotency-Key": request_idempotency_key(payload.crm_request_id),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response = await send(
                self._http,
                "POST",
                url,
                timeout_s=self._timeout_s,
                headers=headers,
                json=payload_to_dict(payload),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamUnavailableError("erp timeout", reason=Reason.ERP_UNAVAILABLE) from exc
        except httpx.InvalidURL as exc:
            raise ValidationFailedError(
                str(exc), reason=Reason.ERP_INVALID_URL, field="base_url"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                type(exc).__name__, reason=Reason.ERP_UNAVAILABLE
            ) from exc
        return _result(response)


def _result(response: httpx.Response) -> ClientRequestResult:
    status = response.status_code
    if status == 429:
        raise rate_limited(response)
    if status in (401, 403):
        raise UpstreamUnavailableError(f"HTTP {status}", reason=Reason.ERP_UNAUTHORIZED)
    if status == 409:
        # Тот же ключ идемпотентности с другим телом (`IDEMPOTENCY_CONFLICT`): данные заявки
        # изменились после первой отправки — ERP ничего не создала и не перезаписала.
        raise ConflictError(
            "ERP: заявка уже отправлялась с другими данными — ничего не создано; "
            "создайте заявку заново",
            reason=Reason.ERP_REQUEST_CONFLICT,
            erp_detail=_detail_of(response),
        )
    if status == 404:
        raise NotFoundError("erp: client is not handed off", reason=Reason.ERP_BAD_RESPONSE)
    if status == 422:
        raise ValidationFailedError(
            f"erp validation error: {response.text[:300]}", reason=Reason.ERP_BAD_RESPONSE
        )
    if status not in (200, 201):
        raise UpstreamUnavailableError(
            f"erp bad response: HTTP {status}", reason=Reason.ERP_BAD_RESPONSE
        )
    try:
        data = response.json()
        return ClientRequestResult(
            erp_company_id=int(data["erp_company_id"]),
            erp_request_id=int(data["erp_request_id"]),
            number=str(data.get("number") or ""),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamUnavailableError(
            f"bad json from erp: {exc}", reason=Reason.ERP_BAD_RESPONSE
        ) from exc


def _detail_of(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", ""))[:64]
    except (ValueError, AttributeError):
        return ""
