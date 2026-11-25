"""«Партнёр» из карточки лида в ERP: `POST /api/integration/v1/partner-applications` (шов
0.10.0, ЛП-1).

ERP заводит заявку кандидата в очередь «Заявки партнёров» (`source = lead`, `source_ref` = номер
лида). Идемпотентно по
номеру лида на стороне ERP: повтор с любым ключом — та же заявка (200). Ключ `Idempotency-Key` —
от лида и тела:
изменённая после сбоя форма не упирается в `IDEMPOTENCY_CONFLICT`. Ошибки: 401/403/5xx/таймаут —
временные
(`erp_unavailable`, лид не тронут, можно повторить), 422 — постоянная (`erp_bad_response`), 429
— пауза `Retry-After`.
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.domain.erp_connector import base_url_problem
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import rate_limited, resolve_connection
from app.integrations.erp_transport import SharedAsyncClient, send
from app.security.secrets_store import SecretsStore
from app.services.settings import SettingsService

_NAMESPACE = uuid.UUID("0b7a4c3e-6d2f-4f0a-9a51-3c8d2e7f1b64")


def partner_idempotency_key(payload: "PartnerApplicationPayload") -> str:
    """Ключ от лида и содержимого: тот же лид с теми же данными — тот же ключ, другие данные —
    новый."""
    digest = hashlib.sha256(
        json.dumps(asdict(payload), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return str(uuid.uuid5(_NAMESPACE, f"crm-partner:{payload.crm_lead_id}:{digest}"))


@dataclass(frozen=True, slots=True)
class PartnerApplicationPayload:
    crm_lead_id: int
    lead_number: str
    company_name: str
    categories_description: str
    contact_name: str
    country: str = "UZ"
    inn: str = ""
    kind: str = "supplier"
    email: str = ""
    phone: str = ""
    language: str = "ru"


@dataclass(frozen=True, slots=True)
class PartnerApplicationResult:
    erp_application_id: int
    status: str
    created: bool


class ErpPartnerClient(Protocol):
    async def create_partner_application(
        self, payload: PartnerApplicationPayload
    ) -> PartnerApplicationResult: ...


class HttpxErpPartnerClient:
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

    async def create_partner_application(
        self, payload: PartnerApplicationPayload
    ) -> PartnerApplicationResult:
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
        url = f"{connection.base_url.rstrip('/')}/api/integration/v1/partner-applications"
        headers = {
            "Authorization": f"Bearer {connection.token}",
            "Idempotency-Key": partner_idempotency_key(payload),
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
                json=asdict(payload),
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


def _result(response: httpx.Response) -> PartnerApplicationResult:
    status = response.status_code
    if status == 429:
        raise rate_limited(response)
    if status in (401, 403):
        raise UpstreamUnavailableError(f"HTTP {status}", reason=Reason.ERP_UNAUTHORIZED)
    if status in (409, 422):
        raise ValidationFailedError(
            f"erp rejected the application: {response.text[:300]}", reason=Reason.ERP_BAD_RESPONSE
        )
    if status not in (200, 201):
        raise UpstreamUnavailableError(
            f"erp bad response: HTTP {status}", reason=Reason.ERP_BAD_RESPONSE
        )
    try:
        data: dict[str, Any] = response.json()
        return PartnerApplicationResult(
            erp_application_id=int(data["erp_application_id"]),
            status=str(data.get("status") or "submitted"),
            created=bool(data.get("created", status == 201)),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamUnavailableError(
            f"bad json from erp: {exc}", reason=Reason.ERP_BAD_RESPONSE
        ) from exc
