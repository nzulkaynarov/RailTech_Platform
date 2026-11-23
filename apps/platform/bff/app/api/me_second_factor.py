"""Профиль: второй фактор входа (ДВ-4, контракт: tag `me`).

Свой фактор настраивает каждый вошедший сотрудник. Решения и секрет — в CRM (`/me/second-factor`);
BFF подставляет название компании для приложения-аутентификатора и переводит отказы CRM в `Error`
с `details.reason` (`second_factor_code_invalid`, `second_factor_not_started`,
`second_factor_already_enabled`, `second_factor_not_enabled`, `secrets_key_missing`).
"""

from typing import Any

import httpx
from fastapi import APIRouter, Request, Response, status

from app.clients import crm_setup
from app.clients.base import BackendUnavailableError
from app.deps import AuthedDep
from app.errors import PlatformError, backend_reason, from_backend
from app.schemas_profile import (
    SecondFactorCodeIn,
    SecondFactorEnabled,
    SecondFactorSetup,
    SecondFactorStatus,
    StepUpOut,
)

router = APIRouter(tags=["me"])

BASE = "/api/v1/me/second-factor"


def _body(response: httpx.Response, ok: int = 200) -> dict[str, Any]:
    if response.status_code == ok:
        body = response.json()
        if isinstance(body, dict):
            return body
    if response.status_code == 409 and backend_reason(response) == "second_factor_required":
        raise PlatformError(
            "CONFLICT",
            "Для вашего доступа второй фактор обязателен.",
            status_code=409,
            source="crm",
            details={"reason": "second_factor_required"},
        )
    if response.status_code == 422:
        reason = backend_reason(response) or "second_factor_code_invalid"
        raise PlatformError(
            "VALIDATION_FAILED",
            "Неверный код." if reason == "second_factor_code_invalid" else "Действие недоступно.",
            status_code=422,
            source="crm",
            details={"reason": reason},
        )
    raise from_backend("crm", response)


@router.get("/me/second-factor", response_model=SecondFactorStatus, operation_id="getSecondFactor")
async def get_second_factor(authed: AuthedDep) -> SecondFactorStatus:
    return SecondFactorStatus.model_validate(_body(await authed.call("crm", "GET", BASE)))


@router.post(
    "/me/second-factor/setup",
    response_model=SecondFactorSetup,
    operation_id="setupSecondFactor",
)
async def setup_second_factor(request: Request, authed: AuthedDep) -> SecondFactorSetup:
    """Секрет и адрес для QR; в приложении запись подписана названием компании из настроек."""
    try:
        issuer = (await crm_setup.fetch_state(request.app.state.crm)).company_name or ""
    except (BackendUnavailableError, PlatformError):
        issuer = ""
    response = await authed.call("crm", "POST", f"{BASE}/setup", json={"issuer": issuer[:60]})
    return SecondFactorSetup.model_validate(_body(response))


@router.post(
    "/me/second-factor/enable",
    response_model=SecondFactorEnabled,
    operation_id="enableSecondFactor",
)
async def enable_second_factor(body: SecondFactorCodeIn, authed: AuthedDep) -> SecondFactorEnabled:
    """Код из приложения включает фактор; резервные коды — в ответе один раз."""
    response = await authed.call("crm", "POST", f"{BASE}/enable", json={"code": body.code})
    return SecondFactorEnabled.model_validate(_body(response))


@router.post(
    "/me/second-factor/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="disableSecondFactor",
)
async def disable_second_factor(body: SecondFactorCodeIn, authed: AuthedDep) -> Response:
    response = await authed.call("crm", "POST", f"{BASE}/disable", json={"code": body.code})
    if response.status_code != 204:
        _body(response, ok=204)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/me/second-factor/step-up", response_model=StepUpOut, operation_id="stepUpSecondFactor"
)
async def step_up_second_factor(body: SecondFactorCodeIn, authed: AuthedDep) -> StepUpOut:
    """Свежий код (ДВ-4б): токен на 5 минут для чувствительных действий — выдача роли и
    подтверждение новых банковских реквизитов (заголовок `X-Step-Up-Token`)."""
    response = await authed.call("crm", "POST", f"{BASE}/step-up", json={"code": body.code})
    return StepUpOut.model_validate(_body(response))
