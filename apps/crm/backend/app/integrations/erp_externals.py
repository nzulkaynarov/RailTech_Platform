"""Клиент ERP для выключателей её внешних сервисов (M3-ERP-06).

`PUT /api/integration/v1/externals/{code}/switch`. Центр внешних сервисов CRM (M3-CRM-12)
останавливает вызовы сервиса ERP — курсов ЦБ, ТН ВЭД, почты, моделей, S3 — этой операцией;
состояние хранит ERP.
Адрес и токен — из коннектора «ERP» (`ErpIntegrationHttp`).
"""

from typing import Protocol

from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.erp_http import ErpIntegrationHttp, bad_response


class ErpSwitchClient(Protocol):
    async def set_switch(self, code: str, *, enabled: bool, reason: str | None) -> None:
        """Включить или выключить сервис ERP `code` (идемпотентно); отказ ERP — доменная ошибка."""
        ...


class HttpxErpSwitchClient(ErpIntegrationHttp):
    async def set_switch(self, code: str, *, enabled: bool, reason: str | None) -> None:
        body: dict[str, object] = {"enabled": enabled}
        if reason and not enabled:
            body["reason"] = reason[:200]
        response = await self._send("PUT", f"/externals/{code}/switch", json=body)
        if response.status_code == 200:
            return
        if response.status_code in (404, 405):
            # Старая ERP без операции (до M3-ERP-06) или чужой код: переключать нечего.
            raise ConflictError(
                "erp does not know this switch",
                reason=Reason.SERVICE_NOT_SWITCHABLE,
                detail="ERP не поддерживает выключатель этого сервиса — обновите ERP",
            )
        if response.status_code == 409:
            raise ConflictError(
                "erp refused the switch",
                reason=Reason.SERVICE_NOT_SWITCHABLE,
                detail="ERP не разрешает выключать этот сервис",
            )
        if response.status_code in (400, 422):
            raise ValidationFailedError(
                f"erp validation error: {response.text[:200]}", reason=Reason.ERP_BAD_RESPONSE
            )
        if response.status_code >= 500:
            raise UpstreamUnavailableError(
                f"erp error: HTTP {response.status_code}", reason=Reason.ERP_UNAVAILABLE
            )
        raise bad_response(response)
