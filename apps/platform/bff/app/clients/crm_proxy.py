"""Вызовы CRM для CRM · База знаний и Admin · Настройки бота (W13-A5, контракт BFF 0.11.0).

`/api/v1/kb/*`, `/sandbox/*`, `/settings*`, `/reply-templates*`, `/export/*`. Вызовы идут от имени
сотрудника через `Authed.call` (токен CRM из сессии). Право на операцию (`kb`, `sandbox`,
`settings`, `reply_templates`, `export`), проверку формата документа, песочницу и сами настройки
решает CRM; здесь — разбор ответов сгенерированными моделями `crm_models`, перевод ошибок CRM в
формат `Error` контракта и два вида вызова, которых нет у остальных экранов: готовое тело
(загрузка файла, BFF его не разбирает) и поток (выгрузка CSV).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.clients.base import Backend
from app.clients.crm_integrations import integration_error
from app.errors import PlatformError, backend_unavailable

log = structlog.get_logger()

Call = Callable[..., Awaitable[httpx.Response]]

# Что из `details` ошибки CRM нужно экрану: правило формата документа, тексты «что исправить» на
# трёх языках, предел размера, пути невалидных полей настроек («greeting.uz»). Остальное (тексты
# исключений CRM) наружу не идёт.
_EXTRA = ("rule", "messages", "max_bytes", "paths", "missing", "detail")


def _extra_details(response: httpx.Response) -> dict[str, Any]:
    try:
        details = response.json()["details"]
    except (ValueError, KeyError, TypeError):
        return {}
    if not isinstance(details, dict):
        return {}
    found: dict[str, Any] = {}
    for key in _EXTRA:
        value = details.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            found[key] = value
        elif key == "messages" and isinstance(value, dict):
            found[key] = {str(k): str(v) for k, v in value.items() if isinstance(v, str)}
        elif key == "paths" and isinstance(value, list):
            found[key] = [str(p) for p in value if isinstance(p, str)][:20]
    return found


def crm_error(response: httpx.Response) -> PlatformError:
    """Ответ CRM не 2xx -> ошибка контракта; решения CRM лишь переводятся."""
    error = integration_error(response)
    extra = _extra_details(response)
    if extra:
        error.body.details = {**(error.body.details or {}), **extra}
    return error


class CrmProxy:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def raw(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        probe: bool = False,
        content: bytes | None = None,
        content_type: str | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        backend: Backend = "crm"
        return await self._call(
            backend,
            method,
            path,
            json=json,
            params=params,
            probe=probe,
            content=content,
            content_type=content_type,
            stream=stream,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: int = 200,
        json: Any = None,
        params: dict[str, Any] | None = None,
        probe: bool = False,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> Any:
        response = await self.raw(
            method,
            path,
            json=json,
            params=params,
            probe=probe,
            content=content,
            content_type=content_type,
        )
        if response.status_code != expected:
            raise crm_error(response)
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
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> T:
        """Ответ CRM, разобранный сгенерированной моделью; не та форма — `BACKEND_UNAVAILABLE`."""
        body = await self.request(
            method,
            path,
            expected=expected,
            json=json,
            params=params,
            probe=probe,
            content=content,
            content_type=content_type,
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
