"""Профиль: личные уведомления от бота и тестовое сообщение (контракт: tag `me`, 0.12.0).

Доступно каждому вошедшему сотруднику: это его собственные настройки (CRM `/me`, `PATCH /me`,
`POST /me/test-notification`). Решения — в CRM; BFF переводит поля и ошибки (Telegram не привязан,
бот не подключён, Telegram отказал) в формат `Error` контракта.
"""

from typing import Any

import httpx
from fastapi import APIRouter, Response, status

from app.clients.crm_integrations import NOT_CONFIGURED_MESSAGE
from app.deps import AuthedDep
from app.errors import PlatformError, backend_code, backend_reason, from_backend
from app.schemas_audit import (
    NotificationSettings,
    NotificationSettingsUpdate,
    to_notification_settings,
)

router = APIRouter(tags=["me"])

ME = "/api/v1/me"
NOT_LINKED_MESSAGE = "Telegram не привязан: привяжите его, чтобы получать личные сообщения бота."
REFUSED_MESSAGE = (
    "Telegram не принял сообщение. Откройте бота, нажмите «Старт» и убедитесь, "
    "что он не заблокирован."
)


def _profile(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise from_backend("crm", response)
    body = response.json()
    if not isinstance(body, dict):
        raise PlatformError(
            "BACKEND_UNAVAILABLE", "Сервис временно недоступен.", status_code=503, source="crm"
        )
    return body


@router.get(
    "/me/notification-settings",
    response_model=NotificationSettings,
    response_model_exclude_none=True,
    operation_id="getNotificationSettings",
)
async def get_notification_settings(authed: AuthedDep) -> NotificationSettings:
    return to_notification_settings(_profile(await authed.call("crm", "GET", ME)))


@router.patch(
    "/me/notification-settings",
    response_model=NotificationSettings,
    response_model_exclude_none=True,
    operation_id="updateNotificationSettings",
)
async def update_notification_settings(
    body: NotificationSettingsUpdate, authed: AuthedDep
) -> NotificationSettings:
    payload = {name: getattr(body, name) for name in body.model_fields_set}
    return to_notification_settings(_profile(await authed.call("crm", "PATCH", ME, json=payload)))


def _test_error(response: httpx.Response) -> PlatformError:
    base = from_backend("crm", response)
    reason = backend_reason(response) or backend_code(response)
    details = {**(base.body.details or {}), **({"reason": reason} if reason else {})}
    if reason == "bot_not_configured":
        return PlatformError(
            "NOT_CONFIGURED",
            NOT_CONFIGURED_MESSAGE,
            status_code=409,
            source="crm",
            details=details,
        )
    if reason == "telegram_not_linked":
        return PlatformError(
            "CONFLICT", NOT_LINKED_MESSAGE, status_code=409, source="crm", details=details
        )
    if reason == "telegram_refused":
        return PlatformError(
            "CONFLICT", REFUSED_MESSAGE, status_code=409, source="crm", details=details
        )
    base.body.details = details
    return base


@router.post(
    "/me/test-notification",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="sendTestNotification",
)
async def send_test_notification(authed: AuthedDep) -> Response:
    response = await authed.call("crm", "POST", f"{ME}/test-notification")
    if response.status_code != 200:
        raise _test_error(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
