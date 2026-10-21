"""Клиент ERP для сотрудников (FIX-11, M3-CRM-06): провижининг и отзыв сессий.

`POST /api/integration/v1/users/provision` (идемпотентно по `crm_user_id`) и
`DELETE /api/integration/v1/users/{crm_user_id}/sessions` — CONTRACTS §2, `erp-integration.yaml`.
Адрес и сервисный токен — те же, что у передачи клиента (коннектор «ERP» в «Подключениях»).
Ошибки — доменные исключения: временные (`UpstreamUnavailableError`) и «коннектор не настроен»
(`ConflictError` с `ERP_NOT_CONFIGURED`) задача повторяет, постоянные (e-mail занят,
`ValidationFailedError`) — нет (решает `ErpAccessService`); пользователю они не показываются,
их видит админ в центре внешних сервисов (ADR-0024). Значения секретов не логируются.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp_http import ErpIntegrationHttp, bad_response


@dataclass(frozen=True, slots=True)
class ProvisionPayload:
    crm_user_id: int
    email: str
    name: str
    role: str
    permissions: tuple[str, ...]
    is_active: bool = True

    def as_json(self) -> dict[str, Any]:
        return {
            "crm_user_id": self.crm_user_id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "permissions": list(self.permissions),
            "is_active": self.is_active,
        }


class ErpUsersClient(Protocol):
    async def provision_user(self, payload: ProvisionPayload) -> int:
        """Создать или обновить сотрудника в ERP; возвращает `erp_user_id`."""
        ...

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        """Отозвать все сессии; `False` — в ERP такого сотрудника нет (отзывать нечего)."""
        ...


class HttpxErpUsersClient(ErpIntegrationHttp):
    async def provision_user(self, payload: ProvisionPayload) -> int:
        response = await self._send(
            "POST",
            "/users/provision",
            json=payload.as_json(),
            extra_headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        if response.status_code == 409:
            raise ConflictError(
                f"erp refused the user: {response.text[:200]}", reason=Reason.ERP_EMAIL_CONFLICT
            )
        if response.status_code in (400, 422):
            raise ValidationFailedError(
                f"erp validation error: {response.text[:300]}", reason=Reason.ERP_BAD_RESPONSE
            )
        if response.status_code not in (200, 201):
            raise bad_response(response)
        try:
            return int(response.json()["erp_user_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailableError(
                f"bad json from erp: {type(exc).__name__}", reason=Reason.ERP_BAD_RESPONSE
            ) from exc

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        response = await self._send("DELETE", f"/users/{int(crm_user_id)}/sessions")
        if response.status_code == 404:
            return False
        if response.status_code != 204:
            raise bad_response(response)
        return True
