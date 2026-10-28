"""Внешние интеграции в CRM для Admin · Внешние интеграции (W13-A1, контракт BFF 0.7.0).

`/api/v1/integrations/*`, `/admin/external-services*`, `/models*`, `/spend`, `/admin/ai-spend`,
`/system/status`, `/system/backups`. Вызовы идут от имени сотрудника через `Authed.call` (токен
CRM из сессии). Право на операцию (`integrations`, `external_services`, `models`, `backups`,
`spend`, `system`), пароль администратора, шифрование секретов и сами проверки связи решает CRM;
здесь — разбор ответов сгенерированными моделями `crm_models` и перевод ошибок CRM в формат
`Error` контракта. Пробы внешних сервисов (`probe=True`) идут с увеличенным таймаутом, а 502 CRM
(«сервис за мной не ответил») приходит как есть: в теле причина, и это результат проверки,
а не сбой CRM.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.clients import crm_models as crm
from app.clients.base import Backend
from app.errors import (
    PlatformError,
    backend_code,
    backend_reason,
    backend_unavailable,
    from_backend,
)
from app.schemas_integrations import CardKey

log = structlog.get_logger()

Call = Callable[..., Awaitable[httpx.Response]]

WRONG_PASSWORD_MESSAGE = "Пароль указан неверно."  # noqa: S105 — текст ошибки, не пароль
NOT_CONFIGURED_MESSAGE = "Подключение ещё не настроено."
SECRETS_KEY_MESSAGE = (
    "На сервере не задан ключ шифрования секретов: сохранить ключи и пароли нельзя. "
    "Задайте его в настройках сервера."
)
NOT_SWITCHABLE_MESSAGE = "У этого сервиса нет выключателя."
INTEGRATION_FAILED_MESSAGE = "Проверка не прошла: сервис не ответил или отказал."

_NOT_CONFIGURED = frozenset(
    {
        "erp_not_configured",
        "smtp_not_configured",
        "bot_not_configured",
        "channel_not_configured",
        "offsite_not_configured",
    }
)
# Поле CRM -> поле контракта (`details.fields`).
_FIELDS = {"base_url": "base_url", "code": "code", "host": "host", "from_email": "from_email"}

# Где в CRM исправляется сервис реестра (`fix_path`) -> карточка экрана Платформы.
# Пути CRM наружу не отдаются.
_FIX_CARDS: tuple[tuple[str, CardKey], ...] = (
    ("/integrations?tab=bot", "telegram"),
    ("/integrations?tab=mail", "mail"),
    ("/integrations?tab=erp", "erp"),
    ("/models", "models"),
    ("/backups", "storage"),
)


def fix_card_of(fix_path: str | None) -> CardKey | None:
    if not fix_path:
        return None
    for prefix, card in _FIX_CARDS:
        if fix_path.startswith(prefix):
            return card
    return None


def integration_error(response: httpx.Response) -> PlatformError:
    """Ответ CRM не 2xx -> ошибка контракта. Решения CRM (право, пароль) только переводятся."""
    status = response.status_code
    reason = backend_reason(response) or backend_code(response)
    if status == 502:
        details: dict[str, Any] = {"backend_status": 502}
        if reason:
            details["reason"] = reason
        return PlatformError(
            "INTEGRATION_FAILED",
            INTEGRATION_FAILED_MESSAGE,
            status_code=502,
            source="crm",
            details=details,
        )
    base = from_backend("crm", response)
    if reason:
        base.body.details = {**(base.body.details or {}), "reason": reason}
    if status == 422 and reason == "wrong_password":
        return PlatformError(
            "WRONG_PASSWORD",
            WRONG_PASSWORD_MESSAGE,
            status_code=422,
            source="crm",
            details={"fields": ["password"], "reason": reason},
        )
    if status == 409:
        if reason in _NOT_CONFIGURED:
            return _replace(base, "NOT_CONFIGURED", NOT_CONFIGURED_MESSAGE)
        if reason == "secrets_key_missing":
            return _replace(base, "SECRETS_KEY_MISSING", SECRETS_KEY_MESSAGE)
        if reason == "service_not_switchable":
            return _replace(base, "SERVICE_NOT_SWITCHABLE", NOT_SWITCHABLE_MESSAGE)
    if status == 422:
        field = _failed_field(response)
        if field:
            base.body.details = {**(base.body.details or {}), "fields": [_FIELDS.get(field, field)]}
        # Что не так с полем (ключ внешней копии: `not_json`, `foreign_token_uri`, …) — код CRM.
        problem = _detail(response, "problem")
        if problem:
            base.body.details = {**(base.body.details or {}), "problem": problem}
    return base


def _replace(base: PlatformError, code: str, message: str) -> PlatformError:
    return PlatformError(
        code, message, status_code=base.status_code, source="crm", details=base.body.details
    )


def _detail(response: httpx.Response, name: str) -> str | None:
    try:
        value = response.json()["details"][name]
    except (ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) and len(value) <= 40 else None


def _failed_field(response: httpx.Response) -> str | None:
    try:
        field = response.json()["details"]["field"]
    except (ValueError, KeyError, TypeError):
        return None
    return field if isinstance(field, str) else None


class CrmIntegrations:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: int = 200,
        json: Any = None,
        params: dict[str, Any] | None = None,
        probe: bool = False,
    ) -> Any:
        backend: Backend = "crm"
        response = await self._call(backend, method, path, json=json, params=params, probe=probe)
        if response.status_code != expected:
            raise integration_error(response)
        try:
            return response.json() if response.content else None
        except ValueError as exc:
            raise backend_unavailable("crm", "bad_response") from exc

    async def get_model[T: BaseModel](
        self,
        model: type[T],
        method: str,
        path: str,
        *,
        expected: int = 200,
        json: Any = None,
        params: dict[str, Any] | None = None,
        probe: bool = False,
    ) -> T:
        """Ответ CRM, разобранный сгенерированной моделью; не та форма — `BACKEND_UNAVAILABLE`."""
        body = await self.request(
            method, path, expected=expected, json=json, params=params, probe=probe
        )
        try:
            return model.model_validate(body)
        except ValidationError as exc:
            log.warning("crm_bad_response", path=path, errors=len(exc.errors()))
            raise backend_unavailable("crm", "bad_response") from exc

    async def get_list[T: BaseModel](
        self, model: type[T], path: str, *, params: dict[str, Any] | None = None
    ) -> list[T]:
        body = await self.request("GET", path, params=params)
        try:
            return TypeAdapter(list[model]).validate_python(body)  # type: ignore[valid-type]
        except ValidationError as exc:
            log.warning("crm_bad_response", path=path, errors=len(exc.errors()))
            raise backend_unavailable("crm", "bad_response") from exc


__all__ = ["CrmIntegrations", "crm", "fix_card_of", "integration_error"]
